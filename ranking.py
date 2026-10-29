"""Score candidates with CLIP and decide which ones to pre-tick.

Plain Python + NumPy + Pillow, no bpy: runs on the worker thread.
"""

from PIL import Image

from . import clip_model, model_store, scoring

MAX_PICKS = 8       # never pre-tick more than this many
# Option C's margin. 0.08 suited the subject score alone; the combined score
# spreads about (subject weight + 1) times as wide, because the style term
# moves roughly like one more subject score. Scaling it keeps the rule meaning
# the same thing whatever weights scoring.py uses.
PICK_MARGIN = 0.08 * (scoring.SUBJECT_WEIGHT + 1)

_model = None  # loading takes a few seconds, so keep it once loaded


def _get_model(models_dir):
    global _model
    if _model is None:
        p = model_store.paths(models_dir)
        _model = clip_model.ClipModel(p["image"], p["text"])
    return _model


def load_rgb(path):
    """Open any image as RGB. Going through RGBA first handles transparency
    cleanly (and avoids Pillow's palette-transparency warning)."""
    with Image.open(path) as img:
        return img.convert("RGBA").convert("RGB")


def score(prompt, image_paths, models_dir):
    """Combined reference score for each image (higher = better reference)."""
    model = _get_model(models_dir)
    vectors = model.encode_images([load_rgb(p) for p in image_paths])
    return scoring.score_images(model, prompt, vectors)["combined"].tolist()


def choose(scores, max_picks=MAX_PICKS, margin=PICK_MARGIN):
    """Option C: the best few, up to max_picks, but only those within margin of the best."""
    if not scores:
        return set()
    best = max(scores)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return {i for i in order[:max_picks] if scores[i] >= best - margin}
