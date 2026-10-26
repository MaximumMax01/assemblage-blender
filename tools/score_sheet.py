"""Show every image in a folder, sorted by how well CLIP thinks it matches a prompt.

Developer tool (dev venv). Run from the repo root:
    & $dev tools\\score_sheet.py stage light
Writes score_sheet.html into the image folder and opens it in your browser.
"""

import argparse
import glob
import html
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clip_model  # noqa: E402

MODEL = "ViT-B-32"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="+", help="what you searched for")
    parser.add_argument("--folder", default="_test_downloads")
    args = parser.parse_args()
    prompt = " ".join(args.prompt)

    paths = sorted(glob.glob(os.path.join(args.folder, "*.jpg")) +
                   glob.glob(os.path.join(args.folder, "*.png")))
    if not paths:
        sys.exit(f"No images in {args.folder}")

    model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx",
                                 f"_models/{MODEL}_text_fp32.onnx")
    phrases = [prompt, f"a photo of a {prompt}"]
    images = [Image.open(p).convert("RGB") for p in paths]
    scores = model.encode_images(images) @ model.encode_texts(phrases).T  # [images, 2]

    order = scores[:, 0].argsort()[::-1]  # best subject score first
    cards = []
    for rank, i in enumerate(order, start=1):
        name = os.path.basename(paths[i])
        cards.append(
            f'<figure><img src="{html.escape(name)}">'
            f'<figcaption>#{rank} &nbsp; subject <b>{scores[i, 0]:.3f}</b>'
            f' &nbsp; photo {scores[i, 1]:.3f}</figcaption></figure>')

    page = f"""<!doctype html><meta charset="utf-8">
<title>Scores: {html.escape(prompt)}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #1e1e1e; color: #ddd; margin: 16px; }}
 main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
 figure {{ margin: 0; background: #2a2a2a; padding: 8px; border-radius: 6px; }}
 img {{ width: 100%; height: 200px; object-fit: contain; background: #111; }}
 figcaption {{ font-size: 14px; padding-top: 6px; }}
</style>
<h1>“{html.escape(prompt)}” — {len(paths)} images, best match first</h1>
<main>{''.join(cards)}</main>"""

    out = os.path.join(args.folder, "score_sheet.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {out}")
    if sys.platform == "win32":
        os.startfile(os.path.abspath(out))


if __name__ == "__main__":
    main()
