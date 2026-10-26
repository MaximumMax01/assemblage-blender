"""Prove the torch-free pipeline (clip_model.py + ONNX) scores like open_clip.

Developer tool: needs the dev venv. Run from the repo root after export_clip.py:
    & $dev tools\\check_clip_parity.py
"""

import glob
import os
import sys

import numpy as np
import open_clip
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clip_model  # noqa: E402  (the repo root had to be added to the path first)

MODEL, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"
PHRASES = ["stage light", "a photo of a stage light", "a technical drawing of a stage light",
           "a photo of a concert stage", "a photo of a cat", "troffer light",
           "acoustic ceiling tile", "backrooms hallway"]


def unit(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main():
    clip, _, ref_preprocess = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
    clip.eval()
    ref_tokenizer = open_clip.get_tokenizer(MODEL)
    images = [Image.open(p).convert("RGB") for p in sorted(glob.glob("_test_downloads/*.jpg"))]

    print("1. Preprocessing: open_clip vs clip_model.preprocess")
    worst = max(np.abs(ref_preprocess(im).numpy() - clip_model.preprocess(im)).max() for im in images)
    print(f"   {len(images)} images, biggest pixel difference {worst:.2e}")

    print("2. Tokenizer: open_clip vs clip_model.Tokenizer")
    same = (ref_tokenizer(PHRASES).numpy() == clip_model.Tokenizer()(PHRASES)).all()
    print(f"   {len(PHRASES)} phrases identical: {same}")

    print("3. End to end: PyTorch open_clip vs clip_model + ONNX fp32")
    with torch.no_grad():
        ref = unit(clip.encode_image(torch.stack([ref_preprocess(im) for im in images])).numpy()) \
            @ unit(clip.encode_text(ref_tokenizer(PHRASES)).numpy()).T
    model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx", f"_models/{MODEL}_text_fp32.onnx")
    ours = model.encode_images(images) @ model.encode_texts(PHRASES).T
    print(f"   worst score drift {np.abs(ours - ref).max():.6f} "
          f"(rule: under 0.005) | identical rankings "
          f"{(ours.argsort(axis=1) == ref.argsort(axis=1)).all(axis=1).mean():.0%}")


if __name__ == "__main__":
    main()
