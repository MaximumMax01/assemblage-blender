"""Show every image in a folder, either ranked by CLIP or blind for labelling.

Developer tool. Run from the repo root:
    python3 tools/score_sheet.py stage light                (ranked by combined score)
    python3 tools/score_sheet.py stage light --by subject   (ranked by subject alone)
    python3 tools/score_sheet.py --folder _labels/office-chair --label
        Blind labelling: shuffled order, no scores, so the current ranking
        can't nudge what you call good. Click once = good close-up/isolated
        (green), twice = good in its real setting (blue), three times = clear.
Writes an HTML page into the image folder and opens it in your browser.
"""

import argparse
import html
import os
import random
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import labels  # noqa: E402  (tools/labels.py: shared by the measuring tools)

MODEL = "ViT-B-32"

PAGE = """<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #1e1e1e; color: #ddd; margin: 16px; }}
 main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
 figure {{ margin: 0; background: #2a2a2a; padding: 8px; border-radius: 6px;
          cursor: pointer; border: 3px solid transparent; }}
 figure.isolated {{ border-color: #3c3; }}
 figure.context {{ border-color: #39f; }}
 img {{ width: 100%; height: 200px; object-fit: contain; background: #111; }}
 figcaption {{ font-size: 13px; padding-top: 6px; }}
 #labels {{ position: sticky; top: 0; background: #1e1e1e; padding: 8px 0; z-index: 1; }}
 textarea {{ width: 100%; height: 3em; background: #111; color: #9f9; }}
</style>
<h1>{heading}</h1>
<div id="labels">{help}
 <button id="copy">Copy list</button> <span id="count">0 marked</span>
 <textarea id="out" readonly></textarea></div>
<main>{cards}</main>
<script>
 const figs = [...document.querySelectorAll("figure")];
 const next = {{"": "isolated", "isolated": "{second}", "context": ""}};
 function update() {{
   const lines = figs.filter(f => f.dataset.label).map(
     f => f.dataset.name + (f.dataset.label === "context" ? " context" : ""));
   document.getElementById("count").textContent = lines.length + " marked";
   document.getElementById("out").value = lines.join("\\n");
 }}
 figs.forEach(f => f.onclick = () => {{
   f.classList.remove(f.dataset.label || "none");
   f.dataset.label = next[f.dataset.label || ""];
   if (f.dataset.label) f.classList.add(f.dataset.label);
   update();
 }});
 document.getElementById("copy").onclick = () => {{
   const box = document.getElementById("out"); box.select();
   navigator.clipboard.writeText(box.value).catch(() => document.execCommand("copy"));
 }};
</script>"""


def card(path, caption):
    name = html.escape(os.path.basename(path))
    return (f'<figure data-name="{name}" data-label=""><img src="{name}">'
            f'<figcaption>{caption}</figcaption></figure>')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="*", help="what you searched for (default: subject.txt)")
    parser.add_argument("--folder", default="_test_downloads")
    parser.add_argument("--by", choices=["combined", "subject", "style"], default="combined")
    parser.add_argument("--label", action="store_true", help="blind labelling sheet")
    args = parser.parse_args()

    paths = labels.image_paths(args.folder)
    if not paths:
        sys.exit(f"No images in {args.folder}")
    prompt = labels.read_subject(args.folder, args.prompt)

    if args.label:
        # A fixed seed: the same shuffle every time, so you can close the page
        # and pick up where you left off.
        order = list(range(len(paths)))
        random.Random(42).shuffle(order)
        cards = [card(paths[i], f"#{n}") for n, i in enumerate(order, start=1)]
        title = heading = f"Label: “{html.escape(prompt)}” ({len(paths)} images)"
        help_text = ("Would you want it on a reference board? Click once = good close-up or "
                     "isolated (green). Twice = good, showing it in its real setting (blue). "
                     "Three times = clear.")
        out_name, second = "label_sheet.html", "context"
    else:
        import clip_model  # only needed for the scored view
        import scoring
        from PIL import Image

        model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx",
                                     f"_models/{MODEL}_text_fp32.onnx")
        images = []
        for p in paths:
            with Image.open(p) as img:
                images.append(img.convert("RGBA").convert("RGB"))
        s = scoring.score_images(model, prompt, model.encode_images(images))
        order = s[args.by].argsort()[::-1]  # best first
        cards = [card(paths[i], f'#{rank} &nbsp; combined <b>{s["combined"][i]:.3f}</b> &nbsp; '
                                f'subject {s["subject"][i]:.3f} &nbsp; style {s["style"][i]:.3f}')
                 for rank, i in enumerate(order, start=1)]
        title = f"{html.escape(prompt)} by {args.by}"
        heading = f"“{html.escape(prompt)}”: {len(paths)} images ranked by {args.by}"
        help_text = "Click every image you'd want on a reference board."
        out_name, second = f"score_sheet_{args.by}.html", ""  # one click type only

    page = PAGE.format(title=title, heading=heading, help=help_text,
                       cards="".join(cards), second=second)
    out = os.path.join(args.folder, out_name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {out}")
    webbrowser.open("file://" + os.path.abspath(out))  # works on Mac, Windows and Linux


if __name__ == "__main__":
    main()
