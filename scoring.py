"""What makes a good modeling reference, expressed as CLIP comparisons.

Pure NumPy, no bpy and no package imports, so the Blender extension and the
developer tools share exactly the same scoring.

Phrases chosen by measurement (tools/phrase_test.py) on hand-labelled images,
not by guessing. Version 2.
"""

# Phrases a GOOD reference matches. {s} is replaced by the search subject.
POSITIVE = [
    "a product photo of a {s} on a plain background",  # AUC 0.80 on "stage light"
    "a {s} isolated on a white background",            # AUC 0.77
]

# Phrases a POOR reference matches (low AUC = reliably finds bad images).
NEGATIVE = [
    "a wide shot of a large scene",        # AUC 0.29
    "an abstract background",              # AUC 0.37
    "a collage of many different images",  # AUC 0.40
    "a watermarked stock photo",           # AUC 0.42
]

SUBJECT_WEIGHT = 1.0   # provisional: confirm with phrase_test on a second subject
NEGATIVE_WEIGHT = 1.0


def score_images(model, subject, image_vectors, positive=None, negative=None,
                 subject_weight=None, negative_weight=None):
    """Score unit image vectors [n, 512]. Returns arrays: subject, style, combined.

    The optional arguments let tools/phrase_test.py try other phrases and
    weights through exactly this same code.
    """
    positive = POSITIVE if positive is None else positive
    negative = NEGATIVE if negative is None else negative
    sw = SUBJECT_WEIGHT if subject_weight is None else subject_weight
    nw = NEGATIVE_WEIGHT if negative_weight is None else negative_weight

    texts = [subject] + [p.format(s=subject) for p in positive] + list(negative)
    sims = image_vectors @ model.encode_texts(texts).T  # [n, len(texts)]

    n_pos = len(positive)
    subject_score = sims[:, 0]                    # "is it the thing?"
    good = sims[:, 1:1 + n_pos].mean(axis=1)      # "does it look like a good reference?"
    bad = sims[:, 1 + n_pos:].mean(axis=1)        # "does it look like a known bad kind?"
    style = good - nw * bad
    combined = sw * subject_score + style
    return {"subject": subject_score, "style": style, "combined": combined}
