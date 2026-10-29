"""Show every image in a folder ranked by CLIP, with all three scores.

Developer tool (dev venv). Run from the repo root:
    & $dev tools\\score_sheet.py stage light              (ranked by combined score)
    & $dev tools\\score_sheet.py stage light --by subject (the old ranking)
Writes score_sheet_<by>.html into the image folder and opens it.
"""

import argparse
import glob
import html
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clip_model  # noqa: E402
import scoring  # noqa: E402

MODEL = "ViT-B-32"


def load_rgb(path):
    with Image.open(path) as img:
        return img.convert("RGBA").convert("RGB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="+", help="what you searched for")
    parser.add_argument("--folder", default="_test_downloads")
    parser.add_argument("--by", choices=["combined", "subject", "style"], default="combined")
    args = parser.parse_args()
    prompt = " ".join(args.prompt)

    paths = sorted(glob.glob(os.path.join(args.folder, "*.jpg")) +
                   glob.glob(os.path.join(args.folder, "*.png")))
    if not paths:
        sys.exit(f"No images in {args.folder}")

    model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx",
                                 f"_models/{MODEL}_text_fp32.onnx")
    s = scoring.score_images(model, prompt, model.encode_images([load_rgb(p) for p in paths]))

    order = s[args.by].argsort()[::-1]  # best first
    cards = []
    for rank, i in enumerate(order, start=1):
        cards.append(
            f'<figure data-name="{html.escape(os.path.basename(paths[i]))}">'
            f'<img src="{html.escape(os.path.basename(paths[i]))}">'
            f'<figcaption>#{rank} &nbsp; combined <b>{s["combined"][i]:.3f}</b>'
            f' &nbsp; subject {s["subject"][i]:.3f} &nbsp; style {s["style"][i]:.3f}'
            f'</figcaption></figure>')

    page = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(prompt)} by {args.by}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #1e1e1e; color: #ddd; margin: 16px; }}
 main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
 figure {{ margin: 0; background: #2a2a2a; padding: 8px; border-radius: 6px; }}
 img {{ width: 100%; height: 200px; object-fit: contain; background: #111; }}
 figcaption {{ font-size: 13px; padding-top: 6px; }}
 figure {{ cursor: pointer; border: 3px solid transparent; }}
 figure.good {{ border-color: #3c3; }}
 #labels {{ position: sticky; top: 0; background: #1e1e1e; padding: 8px 0; z-index: 1; }}
 textarea {{ width: 100%; height: 3em; background: #111; color: #9f9; }}
</style>
<h1>“{html.escape(prompt)}”: {len(paths)} images ranked by {args.by}</h1>
<div id="labels">Click every image you'd want on a reference board.
 <button id="copy">Copy list</button> <span id="count">0 marked</span>
 <textarea id="out" readonly></textarea></div>
<main>{''.join(cards)}</main>
<script>
 const figs = [...document.querySelectorAll("figure")];
 function update() {{
   const good = figs.filter(f => f.classList.contains("good")).map(f => f.dataset.name);
   document.getElementById("count").textContent = good.length + " marked";
   document.getElementById("out").value = good.join("\\n");
 }}
 figs.forEach(f => f.onclick = () => {{ f.classList.toggle("good"); update(); }});
 document.getElementById("copy").onclick = () => {{
   const box = document.getElementById("out"); box.select();
   navigator.clipboard.writeText(box.value).catch(() => document.execCommand("copy"));
 }};
</script>"""

    out = os.path.join(args.folder, f"score_sheet_{args.by}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {out}")
    if sys.platform == "win32":
        os.startfile(os.path.abspath(out))


if __name__ == "__main__":
    main()
