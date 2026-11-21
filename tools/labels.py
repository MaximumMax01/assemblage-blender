"""Read a labelled set written by score_sheet.py --label.

good.txt has one image per line:
    3f2a9c...jpg            a good close-up / isolated reference
    3f2a9c...jpg context    a good reference showing the thing in its real setting
Unlisted images are not good references.
"""

import glob
import os


def image_paths(folder):
    return sorted(glob.glob(os.path.join(folder, "*.jpg")) +
                  glob.glob(os.path.join(folder, "*.png")))


def read_subject(folder, words=None):
    """The search words: from the command line if given, else subject.txt."""
    if words:
        return " ".join(words)
    path = os.path.join(folder, "subject.txt")
    if not os.path.exists(path):
        raise SystemExit(f"Say what was searched, or put it in {path}")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def read_labels(folder):
    """Returns {file name: "isolated" or "context"} for every image marked good."""
    labels = {}
    with open(os.path.join(folder, "good.txt"), encoding="utf-8-sig") as f:
        for line in f:
            parts = line.split()
            if parts:
                labels[parts[0]] = "context" if parts[1:2] == ["context"] else "isolated"
    return labels
