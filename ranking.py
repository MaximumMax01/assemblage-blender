"""Score candidates with CLIP and decide which ones to pre-tick.

Plain Python + NumPy + Pillow, no bpy: runs on the worker thread.
"""

from PIL import Image

from . import clip_model, model_store

MAX_PICKS = 8      # never pre-tick more than this many
PICK_MARGIN = 0.08  # ...and only images scoring within this of the best one

_model = None  # loading takes a few seconds, so keep it once loaded


def _get_model(models_dir):
    global _model
    if _model is None:
        p = model_store.paths(models_dir)
        _model = clip_model.ClipModel(p["image"], p["text"])
    return _model


def score(prompt, image_paths, models_dir):
    """Cosine similarity of each image to the bare prompt (the 'subject' score)."""
    model = _get_model(models_dir)
    text = model.encode_texts([prompt])
    images = [Image.open(p).convert("RGB") for p in image_paths]
    return (model.encode_images(images) @ text.T)[:, 0].tolist()


def choose(scores, max_picks=MAX_PICKS, margin=PICK_MARGIN):
    """Option C: the best few, up to max_picks, but only those within margin of the best."""
    if not scores:
        return set()
    best = max(scores)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return {i for i in order[:max_picks] if scores[i] >= best - margin}
