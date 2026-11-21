"""Does each "show me" mode deliver its kind of image? Compares them on labelled sets.

The modes match a choice the user makes in the panel:
  product shots   rank by the shipped product-photo phrases (today's behaviour)
  in real setting rank by the context phrases instead
  mix             CLIP sorts images into the two kinds, the board takes 4 + 4
"subject only" is the plain baseline every mode should beat at its own job.

Developer tool. Run from the repo root, after labelling with score_sheet.py --label:
    python3 tools/rank_compare.py _labels/office-chair _labels/lap-siding _labels/wall-fountain

For every method it reports, per set and in total:
  AUC          does it rank good images above the rest overall? (1.0 perfect, 0.5 coin flip)
  top 8        how many of the first 8 are good, split into close-up / in context
  auto-picks   what the add-on would actually pre-tick, and how many of those are good
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
from phrase_test import auc  # noqa: E402  (same AUC everywhere, so numbers compare)

MODEL = "ViT-B-32"
MAX_PICKS = 8

ISOLATED = scoring.POSITIVE  # the shipped "good reference" phrases
CONTEXT = [  # new candidates. Guesses until phrase_test.py says otherwise.
    "a photo of a {s} in a real-world setting",
    "a photo of a {s} installed and in use",
]
NEG_ALL = scoring.NEGATIVE
# The context methods drop "a wide shot of a large scene": it punishes exactly
# the in-setting photos they are trying to find.
NEG_NO_WIDE = [p for p in scoring.NEGATIVE if "wide shot" not in p]


def by_margin(scores, margin):
    """The shipped pick rule (ranking.choose): best few within margin of the best."""
    order = np.argsort(scores)[::-1][:MAX_PICKS]
    return [i for i in order if scores[i] >= scores.max() - margin]


def quota(base_iso, base_ctx, is_ctx, per_kind=MAX_PICKS // 2):
    """Half the board from each kind (each ranked by its own score), then fill
    any empty places with the best of what's left."""
    picks = []
    for base, members in ((base_iso, ~is_ctx), (base_ctx, is_ctx)):
        idx = np.flatnonzero(members)
        picks += list(idx[np.argsort(base[idx])[::-1][:per_kind]])
    best_overall = np.argsort(np.maximum(base_iso, base_ctx))[::-1]
    picks += [i for i in best_overall if i not in picks][:MAX_PICKS - len(picks)]
    return picks


def centred(x):
    """Subtract the average over this search's images.

    The two phrase groups have different baselines: every image might score
    0.24 on one group and 0.21 on the other just because of the wording.
    Comparing raw numbers would then call almost everything the first kind.
    Centring each group first asks the fair question: is this image MORE
    like an isolated shot than the other images are, or more like an
    in-setting shot?
    """
    return x - x.mean()


def evaluate(model, folder):
    subject = labels.read_subject(folder)
    marked = labels.read_labels(folder)
    paths = labels.image_paths(folder)
    names = [os.path.basename(p) for p in paths]
    good = np.array([n in marked for n in names])
    good_ctx = np.array([marked.get(n) == "context" for n in names])

    images = []
    for p in paths:
        with Image.open(p) as img:
            images.append(img.convert("RGBA").convert("RGB"))
    vectors = model.encode_images(images)

    def sims(phrases):
        return vectors @ model.encode_texts([p.format(s=subject) for p in phrases]).T

    subj = sims(["{s}"])[:, 0]
    iso, ctx = centred(sims(ISOLATED).mean(axis=1)), centred(sims(CONTEXT).mean(axis=1))
    bad_all, bad_nw = sims(NEG_ALL).mean(axis=1), sims(NEG_NO_WIDE).mean(axis=1)
    is_ctx = ctx > iso  # CLIP's guess at each image's kind

    print(f"\n{folder}: “{subject}”, {len(paths)} images, {good.sum()} good "
          f"({(good & ~good_ctx).sum()} close-up, {good_ctx.sum()} in context)")
    if good.sum() < 5:
        print("   (under 5 good images: too few to tell methods apart)")
    agree = (is_ctx[good] == good_ctx[good]).sum()
    print(f"   CLIP sorted {agree} of {good.sum()} good images into the same kind you did")

    margin = 0.08 * (scoring.SUBJECT_WEIGHT + 1)
    ranked = {  # name: (scores, pick margin)
        "subject only (baseline)": (subj, 0.08),
        "product shots (shipped)": (subj + iso - scoring.NEGATIVE_WEIGHT * bad_all, margin),
        "in real setting": (subj + ctx - scoring.NEGATIVE_WEIGHT * bad_nw, margin),
    }
    results = {}
    for name, (scores, m) in ranked.items():
        top = list(np.argsort(scores)[::-1][:MAX_PICKS])
        results[name] = (auc(scores, good), top, by_margin(scores, m))
    q = quota(subj + iso - scoring.NEGATIVE_WEIGHT * bad_nw,
              subj + ctx - scoring.NEGATIVE_WEIGHT * bad_nw, is_ctx)
    results["mix: 4 product + 4 setting"] = (None, q, q)

    for name, (a, top, picks) in results.items():
        top, picks = np.array(top, dtype=int), np.array(picks, dtype=int)
        auc_text = "  n/a" if a is None else f"{a:.2f}"
        print(f"   {name:<31} AUC {auc_text} | top 8: {good[top].sum()} good "
              f"({(good & ~good_ctx)[top].sum()} close-up, {good_ctx[top].sum()} context)"
              f" | auto-picks: {good[picks].sum()}/{len(picks)} good")
    return {name: (good[np.array(top, dtype=int)].sum(), good_ctx[np.array(top, dtype=int)].sum())
            for name, (_, top, _) in results.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+", help="labelled sets, e.g. _labels/office-chair")
    args = parser.parse_args()
    model = clip_model.ClipModel(f"_models/{MODEL}_image_fp32.onnx",
                                 f"_models/{MODEL}_text_fp32.onnx")
    totals = {}
    for folder in args.folders:
        for name, (g, c) in evaluate(model, folder).items():
            tg, tc = totals.get(name, (0, 0))
            totals[name] = (tg + g, tc + c)

    n = MAX_PICKS * len(args.folders)
    print(f"\nTotal over {len(args.folders)} sets (good images in the top 8 of each, out of {n}):")
    for name, (g, c) in totals.items():
        print(f"   {name:<31} {g:>3} good, {c} of them in context")


if __name__ == "__main__":
    main()
