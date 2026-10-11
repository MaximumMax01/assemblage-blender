"""Lay out chosen images and write them to a PureRef (.pur) board.

Plain Python + Pillow, no bpy. Adapted from the old backend/board_builder.py.
"""

import os
from io import BytesIO

from PIL import Image

try:
    from .layout import justified_rows      # inside Blender (as part of the package)
    from .purformat import items
    from .purformat.purformat import PurFile
    from .purformat.write import write_pur_file
except ImportError:
    from layout import justified_rows       # run directly from PowerShell
    from purformat import items
    from purformat.purformat import PurFile
    from purformat.write import write_pur_file

MAX_EDGE = 1400  # downscale bigger images so the .pur file stays a sane size


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


def build_board(entries, output_path):
    """Write a .pur board from (path, label, source_url) entries, in order.

    Consecutive entries with the same label form a group.
    """
    if not entries:
        raise ValueError("No images selected.")

    pur_file = PurFile()
    pur_file.images = [_to_pur_image(path, f"{label} - {url}"[:200], url)
                       for path, label, url in entries]

    aspects = []
    for (path, label, url), image in zip(entries, pur_file.images):
        t = image.transforms[0]
        aspects.append((t.width / t.height, label))
    for image, (cx, cy, w, h) in zip(pur_file.images, justified_rows(aspects)):
        t = image.transforms[0]
        t.scale_to_height(h)
        t.x, t.y = cx, cy  # PureRef positions items by their centre

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    # Not pur_file.write(): that method does `from purformat.write import ...`,
    # an absolute import that only works when purformat's parent folder is on
    # sys.path. Inside Blender it isn't, so we call the writer directly.
    write_pur_file(pur_file, output_path)
    return output_path


if __name__ == "__main__":
    import glob

    paths = sorted(glob.glob("_test_downloads/*.jpg") + glob.glob("_test_downloads/*.png"))[:12]
    out = build_board([(p, "test", "https://example.com/" + os.path.basename(p)) for p in paths],
                      "_test_downloads/test_board.pur")
    size_mb = os.path.getsize(out) / 1e6
    print(f"Wrote {len(paths)} images to {out} ({size_mb:.1f} MB)")
