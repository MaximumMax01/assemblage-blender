"""Explore CLIP ViT-B-32 in PyTorch: size, preprocessing, tokens, embeddings.

Developer tool: needs the dev venv (torch + open_clip). Never shipped.
"""

import glob
import sys

import open_clip
import torch
from PIL import Image

MODEL, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"


def count(params):
    return sum(p.numel() for p in params)


def main():
    print("Loading model (the first run may download ~600 MB)...")
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
    tokenizer = open_clip.get_tokenizer(MODEL)
    model.eval()

    # 1. How big is it?
    total = count(model.parameters())
    image_side = count(model.visual.parameters())
    print(f"\n1. PARAMETERS: total {total:,} | image encoder {image_side:,} "
          f"| text side {total - image_side:,}")
    print(f"   at 4 bytes each (fp32): {total * 4 / 1e6:.0f} MB")

    # 2. What exactly happens to an image before the model sees it?
    print("\n2. IMAGE PREPROCESSING (the ONNX version must copy this exactly):")
    print(preprocess)

    # 3. What does text look like to the model?
    phrase = "cat"
    tokens = tokenizer([phrase])
    ids = tokens[0].tolist()
    print(f"\n3. TOKENS for {phrase!r}: shape {tuple(tokens.shape)}")
    print(f"   non-zero ids: {[t for t in ids if t != 0]}")
    print(f"   followed by {ids.count(0)} zeros of padding")

    # 4 + 5. Embeddings and similarity
    path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("_test_downloads/*.jpg"))[0]
    image = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)  # [1, 3, 224, 224]
    phrases = ["a photo of a stage light", "a technical drawing of a stage light",
               "a photo of a concert stage", "a photo of a cat"]
    with torch.no_grad():
        img = model.encode_image(image)
        txt = model.encode_text(tokenizer(phrases))

    print(f"\n4. EMBEDDINGS: image {tuple(img.shape)}, text {tuple(txt.shape)}")
    print(f"   image vector length before normalizing: {img.norm().item():.3f}")
    img = img / img.norm(dim=-1, keepdim=True)
    txt = txt / txt.norm(dim=-1, keepdim=True)
    print(f"   after normalizing: {img.norm().item():.3f}")

    sims = (img @ txt.T)[0]  # one dot product per phrase
    print(f"\n5. COSINE SIMILARITY for {path}:")
    for text, score in sorted(zip(phrases, sims.tolist()), key=lambda pair: -pair[1]):
        print(f"   {score:.3f}  {text}")


if __name__ == "__main__":
    main()