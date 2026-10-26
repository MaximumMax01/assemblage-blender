"""Export CLIP's image and text encoders to ONNX, make int8 versions, and
measure how far each version's scores drift from PyTorch.

Developer tool: needs the dev venv (torch, open_clip, onnx, onnxruntime).
Run from the repo root:  & $dev tools\\export_clip.py
"""

import argparse
import glob
import os
import time

import numpy as np
import onnxruntime as ort
import open_clip
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.quantization.shape_inference import quant_pre_process
from PIL import Image

PHRASES = ["stage light", "a photo of a stage light", "a technical drawing of a stage light",
           "a photo of a concert stage", "a photo of a cat"]


class ImageEncoder(torch.nn.Module):
    """Gives encode_image a forward(), the method the exporter records."""
    def __init__(self, clip):
        super().__init__()
        self.clip = clip

    def forward(self, pixels):
        return self.clip.encode_image(pixels)


class TextEncoder(torch.nn.Module):
    def __init__(self, clip):
        super().__init__()
        self.clip = clip

    def forward(self, tokens):
        return self.clip.encode_text(tokens)


def export(module, example, path, input_name, output_name):
    """Record `module` running on `example` and save it as one .onnx file."""
    batch = torch.export.Dim("batch", min=1, max=1024)
    try:
        torch.onnx.export(module, (example,), path,
                          input_names=[input_name], output_names=[output_name],
                          dynamic_shapes={input_name: {0: batch}},
                          dynamo=True, external_data=False)
        return "dynamo"
    except Exception as exc:
        print(f"   new exporter failed ({type(exc).__name__}: {str(exc)[:200]}); trying legacy")
        torch.onnx.export(module, (example,), path,
                          input_names=[input_name], output_names=[output_name],
                          dynamic_axes={input_name: {0: "batch"}, output_name: {0: "batch"}},
                          dynamo=False, opset_version=18)
        return "legacy"


def unit(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="ViT-B-32")
    parser.add_argument("--pretrained", default="laion2b_s34b_b79k")
    parser.add_argument("--out", default="_models")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print(f"1. Loading {args.model} / {args.pretrained}...")
    clip, _, preprocess = open_clip.create_model_and_transforms(args.model, pretrained=args.pretrained)
    clip.eval()
    tokenizer = open_clip.get_tokenizer(args.model)
    image_enc, text_enc = ImageEncoder(clip).eval(), TextEncoder(clip).eval()

    paths = sorted(glob.glob("_test_downloads/*.jpg"))[:8]
    images = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in paths])
    tokens = tokenizer(PHRASES)
    print(f"   {len(paths)} test images, {len(PHRASES)} test phrases")

    # The reference answers every ONNX version must reproduce.
    with torch.no_grad():
        ref_img = image_enc(images).numpy()
        ref_txt = text_enc(tokens).numpy()
    ref_scores = unit(ref_img) @ unit(ref_txt).T  # [images, phrases] cosine scores

    print("\n2. Exporting fp32 (full precision)...")
    files = {}
    for kind, module, example, name in [("image", image_enc, images[:2], "pixels"),
                                        ("text", text_enc, tokens[:2], "tokens")]:
        path = os.path.join(args.out, f"{args.model}_{kind}_fp32.onnx")
        with torch.no_grad():
            # Not just "embedding": the text encoder already has an internal
            # value with that name (from its token-table lookup), and ONNX
            # requires every name in the graph to be unique.
            how = export(module, example, path, name, f"{kind}_embeds")
        ort.InferenceSession(path, providers=["CPUExecutionProvider"])  # fail fast if invalid
        files[("fp32", kind)] = path
        print(f"   {kind}: {os.path.getsize(path) / 1e6:.0f} MB ({how} exporter)")

    print("\n3. Making int8 versions (weights rounded to 256 levels)...")
    for kind in ("image", "text"):
        src = files[("fp32", kind)]
        dst = src.replace("_fp32", "_int8")
        prepped = src.replace("_fp32", "_prep")
        try:
            # The step the warning asked for: work out every tensor's shape and
            # tidy the graph first, so the quantizer knows what it's rounding.
            quant_pre_process(src, prepped)
            source = prepped
        except Exception as exc:
            print(f"   {kind}: pre-processing failed ({type(exc).__name__}), quantizing without it")
            source = src
        try:
            quantize_dynamic(source, dst, weight_type=QuantType.QInt8)
            files[("int8", kind)] = dst
            print(f"   {kind}: {os.path.getsize(dst) / 1e6:.0f} MB")
        except Exception as exc:
            print(f"   {kind}: int8 failed ({type(exc).__name__}: {str(exc)[:200]})")

    print(f"\n4. Drift from PyTorch (onnxruntime {ort.__version__}):")
    for precision in ("fp32", "int8"):
        if (precision, "image") not in files or (precision, "text") not in files:
            continue
        img_sess = ort.InferenceSession(files[(precision, "image")], providers=["CPUExecutionProvider"])
        txt_sess = ort.InferenceSession(files[(precision, "text")], providers=["CPUExecutionProvider"])

        # Batch 1 then the full batch: proves the batch size really is variable.
        img_sess.run(None, {"pixels": images[:1].numpy()})
        img = img_sess.run(None, {"pixels": images.numpy()})[0]
        txt = txt_sess.run(None, {"tokens": tokens.numpy()})[0]
        scores = unit(img) @ unit(txt).T

        drift = np.abs(scores - ref_scores).max()
        same_rank = (scores.argsort(axis=1) == ref_scores.argsort(axis=1)).all(axis=1).mean()
        start = time.perf_counter()
        img_sess.run(None, {"pixels": images.numpy()})
        ms = (time.perf_counter() - start) / len(images) * 1000

        print(f"   {precision}: worst score drift {drift:.5f} | images with identical phrase "
              f"ranking {same_rank:.0%} | {ms:.0f} ms per image")

    print("\n5. Reference scores (PyTorch), first image:")
    for phrase, s in zip(PHRASES, ref_scores[0]):
        print(f"   {s:.3f}  {phrase}")


if __name__ == "__main__":
    main()