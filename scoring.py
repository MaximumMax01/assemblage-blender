"""What makes a good modeling reference, expressed as CLIP comparisons.

Pure NumPy, no bpy and no package imports, so the Blender extension and the
developer tools share exactly the same scoring.

Phrases and weights chosen by measurement (tools/phrase_test.py) on
hand-labelled searches for "stage light" and "office chair", not by guessing.
Version 2.1.
"""

# Phrases a GOOD reference matches. {s} is replaced by the search subject.
POSITIVE = [  # AUC on stage light / office chair (1.0 = always finds good ones)
    "a product photo of a {s} on a plain background",  # 0.80 / 0.88
    "a {s} isolated on a white background",            # 0.77 / 0.80
]

# Phrases a POOR reference matches (low AUC = reliably finds bad images).
NEGATIVE = [  # low AUC on both = reliably finds bad images
    "a wide shot of a large scene",        # 0.29 / 0.45
    "a collage of many different images",  # 0.40 / 0.45
    "a watermarked stock photo",           # 0.42 / 0.39
    # dropped "an abstract background": 0.37 on stage light but 0.59 on chairs,
    # i.e. it pointed the wrong way on the second subject.
]

# Office chair: 1.0/0.5 gave AUC 0.91 with 5 of 9 good in the top 8, as good as
# any setting within noise. Stage light: extra subject weight hurt (subject
# alone 0.68 vs style alone 0.79), so 1.0 is the safer middle than 2.0.
SUBJECT_WEIGHT = 1.0
NEGATIVE_WEIGHT = 0.5


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
