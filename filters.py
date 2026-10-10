"""Cheap quality filters: reject junk before anyone (or CLIP) looks at it.

Plain Python + NumPy + Pillow, no bpy: runs on the worker thread.
"""

import numpy as np
from PIL import Image

WORK_DIM = 800            # measure sharpness at this size so scores are comparable
MIN_DIM = 500             # shorter side must be at least this many pixels
MAX_ASPECT = 5.0          # reject panoramas/strips longer than 5:1
MIN_LAPLACIAN = 25.0      # the drawing-friendly threshold from the old ortho slot
DHASH_DUPE_DISTANCE = 5   # hashes this close (out of 64 bits) count as the same picture


def laplacian_variance(gray):
    """Sharpness: variance of the discrete Laplacian (matches cv2.Laplacian ksize=1)."""
    g = np.pad(gray.astype(np.float64), 1, mode="reflect")
    lap = (g[:-2, 1:-1] + g[2:, 1:-1]      # pixel above + pixel below
           + g[1:-1, :-2] + g[1:-1, 2:]    # pixel left  + pixel right
           - 4 * g[1:-1, 1:-1])            # minus 4 x the pixel itself
    return float(lap.var())


def dhash(img, size=8):
    """64-bit difference hash: is each pixel brighter than its right-hand neighbour?"""
    small = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    arr = np.asarray(small, dtype=np.int16)
    return (arr[:, 1:] > arr[:, :-1]).flatten()


def check_image(path):
    """Return (image, None) if it passes, or (None, reason) if it doesn't."""
    try:
        img = Image.open(path)
        img = img.convert("RGB")
    except Exception as exc:
        return None, f"unreadable ({type(exc).__name__})"

    w, h = img.size
    if min(w, h) < MIN_DIM:
        return None, f"too small ({w}x{h})"
    if max(w / h, h / w) > MAX_ASPECT:
        return None, f"too stretched ({w}x{h})"

    work = img
    if max(w, h) > WORK_DIM:
        scale = WORK_DIM / max(w, h)
        work = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                          Image.Resampling.LANCZOS)
    sharpness = laplacian_variance(np.asarray(work.convert("L")))
    if sharpness < MIN_LAPLACIAN:
        return None, f"blurry (sharpness {sharpness:.0f})"

    return img, None


def filter_all(downloaded):
    """Run every check, then drop near-duplicates. Returns (kept, rejected)."""
    kept, rejected, hashes = [], [], []
    for item in downloaded:
        img, reason = check_image(item["path"])
        if img is None:
            rejected.append((item, reason))
            continue
        h = dhash(img)
        if any(int(np.count_nonzero(h != prev)) <= DHASH_DUPE_DISTANCE for prev in hashes):
            rejected.append((item, "duplicate"))
            continue
        hashes.append(h)
        kept.append(item)
    return kept, rejected


if __name__ == "__main__":
    import glob
    import os
    import sys

    folder = sys.argv[1] if len(sys.argv) > 1 else "_test_downloads"
    paths = sorted(glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")))
    kept, rejected = filter_all([{"path": p} for p in paths])
    print(f"kept {len(kept)} of {len(paths)}")
    for item, reason in rejected:
        print(f"  rejected {os.path.basename(item['path'])}: {reason}")