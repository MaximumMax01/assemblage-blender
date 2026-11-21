"""Measure which phrases and formulas actually separate good references from bad.

Developer tool. Label a set first (score_sheet.py --label), save the copied
list as good.txt in that folder (Mac: pbpaste > _labels/office-chair/good.txt),
then:   python3 tools/phrase_test.py --folder _labels/office-chair
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clip_model  # noqa: E402
import scoring  # noqa: E402

import labels  # noqa: E402  (tools/labels.py)

MODEL = "ViT-B-32"

CANDIDATES = [  # {s} = the subject. Kept generic on purpose: they must work for any subject.
    "{s}",
    "a photo of a {s}",
    "a product photo of a {s} on a plain background",
    "a {s} isolated on a white background",
    "a clear, well-lit photo of a single {s}",
    "a close-up detail photo of a {s}",
    "a {s}, the whole object visible",
    "a photo of a {s} as a physical object",
    "a technical drawing of a {s}",
    "an atmospheric scene with dramatic lighting",
    "a digital art render",
    "an abstract background",
    "an infographic with text",
    "a collage of many different images",
    "a watermarked stock photo",
    "a dark, blurry photo",
    "a crowd of people",
    "a wide shot of a large scene",
    "a photo of a {s} in a real-world setting",   # context candidates
    "a photo of a {s} installed and in use",
]


V1_POSITIVE = ["a photo of a {s}", "a product photo of a {s} on a plain background",
               "a clear, well-lit photo of a single {s}", "a close-up detail photo of a {s}"]
V1_NEGATIVE = ["an atmospheric scene with dramatic lighting", "a digital art render",
               "an infographic with text", "a collage of many different images",
               "a watermarked stock photo", "a dark, blurry photo", "a crowd of people"]


def auc(scores, good):
    """Chance that a random GOOD image outscores a random other image.
    1.0 = perfect separation, 0.5 = no better than a coin flip, 0.0 = backwards."""
    g, b = scores[good], scores[~good]
    wins = (g[:, None] > b[None, :]).sum() + 0.5 * (g[:, None] == b[None, :]).sum()
    return wins / (len(g) * len(b))


def top8(scores, good):
    return int(good[np.argsort(scores)[::-1][:8]].sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="*", help="what was searched (default: subject.txt)")
    parser.add_argument("--folder", default="_test_downloads")
    args = parser.parse_args()
    s = labels.read_subject(args.folder, args.prompt)

    paths = labels.image_paths(args.folder)
    names = labels.read_labels(args.folder)  # both kinds of good count as good here
    good = np.array([os.path.basename(p) in names for p in paths])
    print(f"{len(paths)} images, {good.sum()} marked good\n")

    model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx",
                                 f"_models/{MODEL}_text_fp32.onnx")
    images = []
    for p in paths:
        with Image.open(p) as img:
            images.append(img.convert("RGBA").convert("RGB"))
    vectors = model.encode_images(images)

    print("1. Each phrase on its own (AUC: 1.0 = finds good ones, 0.0 = finds bad ones)")
    texts = [c.format(s=s) for c in CANDIDATES]
    sims = vectors @ model.encode_texts(texts).T
    for text, col in sorted(zip(texts, sims.T), key=lambda pair: -auc(pair[1], good)):
        print(f"   AUC {auc(col, good):.2f} | good in top 8: {top8(col, good)} | {text}")

    print("\n2. Whole formulas (prefer the SIMPLEST one near the top, not the single best:")
    print("   with this few labels, small differences are mostly luck)")
    rows = [("subject only", scoring.score_images(model, s, vectors)["subject"]),
            ("v1 phrases, 2 x subject, 0.75 x bad",
             scoring.score_images(model, s, vectors, V1_POSITIVE, V1_NEGATIVE, 2.0, 0.75)["combined"])]
    for sw in (0.0, 0.5, 1.0, 2.0):
        for nw in (0.5, 1.0):
            values = scoring.score_images(model, s, vectors, subject_weight=sw, negative_weight=nw)
            rows.append((f"v2 phrases, {sw} x subject, {nw} x bad", values["combined"]))
    for name, values in rows:
        print(f"   AUC {auc(values, good):.2f} | good in top 8: {top8(values, good)} | {name}")


if __name__ == "__main__":
    main()
