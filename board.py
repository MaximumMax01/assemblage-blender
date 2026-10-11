"""Lay out chosen images and write them to a PureRef (.pur) board.

Plain Python + Pillow, no bpy. Adapted from the old backend/board_builder.py.
"""

import os
from io import BytesIO

from PIL import Image

try:
    from .purformat import items            # inside Blender (as part of the package)
    from .purformat.purformat import PurFile
except ImportError:
    from purformat import items             # run directly from PowerShell
    from purformat.purformat import PurFile

MAX_EDGE = 1400      # downscale bigger images so the .pur file stays a sane size
ROW_HEIGHT = 1000    # every image starts this tall (PureRef canvas units)
CANVAS_WIDTH = 4000  # full rows are scaled to exactly this width
GAP = 40             # space between images, and between rows
GROUP_GAP = 200      # extra space between groups (used again once slots return)


def _to_pur_image(path, name, source):
    """Load one image file and wrap it as a PureRef image item."""
    with Image.open(path) as img:
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        scale = MAX_EDGE / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.Resampling.LANCZOS)

    pur_image = items.PurImage()
    with BytesIO() as buf:
        img.save(buf, format="PNG", compress_level=7)
        pur_image.pngBinary = buf.getvalue()

    transform = items.PurGraphicsImageItem()
    transform.reset_crop(img.width, img.height)
    transform.name = name
    transform.source = source
    pur_image.transforms = [transform]
    return pur_image


def pack_rows(groups):
    """Justified rows: full rows span CANVAS_WIDTH; short rows are never enlarged.

    Each group starts on a new row. PureRef positions items by their centre.
    """
    y = 0.0
    for g_index, group in enumerate(groups):
        for t in group:
            t.scale_to_height(ROW_HEIGHT)

        rows, current = [], []
        for t in group:
            current.append(t)
            span = sum(x.width for x in current) + GAP * (len(current) - 1)
            if span >= CANVAS_WIDTH:   # row is full: close it
                rows.append(current)
                current = []
        if current:
            rows.append(current)

        for row in rows:
            content = sum(t.width for t in row)
            available = CANVAS_WIDTH - GAP * (len(row) - 1)
            scale = min(1.0, available / content) if content > 0 else 1.0
            x, height = 0.0, 0.0
            for t in row:
                t.scale(scale)
                t.x = x + t.width / 2
                t.y = y + t.height / 2
                x += t.width + GAP
                height = max(height, t.height)
            y += height + GAP

        if g_index < len(groups) - 1:
            y += GROUP_GAP


def build_board(entries, output_path):
    """Write a .pur board from (path, label, source_url) entries, in order.

    Consecutive entries with the same label form a group.
    """
    if not entries:
        raise ValueError("No images selected.")

    pur_file = PurFile()
    pur_file.images = [_to_pur_image(path, f"{label} - {url}"[:200], url)
                       for path, label, url in entries]

    groups, last_label = [], None
    for (path, label, url), image in zip(entries, pur_file.images):
        if label != last_label:
            groups.append([])
            last_label = label
        groups[-1].extend(image.transforms)
    pack_rows(groups)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    pur_file.write(output_path)
    return output_path


if __name__ == "__main__":
    import glob

    paths = sorted(glob.glob("_test_downloads/*.jpg") + glob.glob("_test_downloads/*.png"))[:12]
    out = build_board([(p, "test", "https://example.com/" + os.path.basename(p)) for p in paths],
                      "_test_downloads/test_board.pur")
    size_mb = os.path.getsize(out) / 1e6
    print(f"Wrote {len(paths)} images to {out} ({size_mb:.1f} MB)")
