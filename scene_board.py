"""Build reference boards inside the user's own scene, far from their work.

Uses bpy, so MAIN THREAD ONLY. Shares its layout math with the PureRef board.
"""

import os

import bpy
from PIL import Image

from .layout import justified_rows

COLLECTION_NAME = "Assemblage References"
REF_ORIGIN = (2000.0, 0.0)  # 2 km out: beyond the viewport's default 1000 m draw distance
UNIT = 1 / 1000             # 1000 canvas units = 1 Blender unit, so each row is ~1 m tall
BOARD_SPACING = 0.5         # gap between boards stacked under each other

# Each viewport's own view from before it jumped to the references, so
# "Back to Model" can put it exactly where it was. Keyed by the area's address.
_saved_views = {}


def get_or_create_collection(scene):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def ref_bounds(collection):
    """(left, top, right, bottom) around every board placed so far, or None."""
    rects = [obj["assemblage_rect"] for obj in collection.all_objects if "assemblage_rect" in obj]
    if not rects:
        return None
    return (min(r[0] for r in rects), max(r[1] for r in rects),
            max(r[2] for r in rects), min(r[3] for r in rects))


def build_scene_board(scene, entries, board_name):
    """entries: list of (path, label, source_url). Returns the new board's bounds."""
    references = get_or_create_collection(scene)

    aspects = []
    for path, label, url in entries:
        with Image.open(path) as img:  # reads only the header: fast
            w, h = img.size
        aspects.append((w / h, label))
    rects = justified_rows(aspects)

    board = bpy.data.collections.new(board_name)
    references.children.link(board)

    origin_x, origin_y = REF_ORIGIN
    previous = ref_bounds(references)
    top = origin_y if previous is None else previous[3] - BOARD_SPACING

    for (path, label, url), (cx, cy, w, h) in zip(entries, rects):
        image = bpy.data.images.load(path, check_existing=True)
        image.pack()  # embed in the .blend: the cache folder gets wiped on the next search

        obj = bpy.data.objects.new(os.path.basename(path), None)  # None = an empty
        obj.empty_display_type = 'IMAGE'
        obj.data = image
        obj.empty_display_size = max(w, h) * UNIT  # the image's longer side
        # Canvas y grows downward; Blender's y grows upward, so flip it.
        x = origin_x + cx * UNIT
        y = top - cy * UNIT
        obj.location = (x, y, 0.0)
        obj["assemblage_source"] = url
        obj["assemblage_rect"] = (x - w / 2 * UNIT, y + h / 2 * UNIT,
                                  x + w / 2 * UNIT, y - h / 2 * UNIT)
        board.objects.link(obj)

    return ref_bounds(board)


def is_at_refs(area):
    return area.as_pointer() in _saved_views


def go_to_refs(area, bounds):
    """Aim this viewport straight down at the references, rotation locked."""
    left, top, right, bottom = bounds
    r3d = area.spaces.active.region_3d
    key = area.as_pointer()
    if key not in _saved_views:  # already there? keep the ORIGINAL view saved
        _saved_views[key] = (r3d.view_perspective, tuple(r3d.view_location),
                             tuple(r3d.view_rotation), r3d.view_distance, r3d.lock_rotation)
    r3d.view_perspective = 'ORTHO'
    r3d.view_rotation = (1.0, 0.0, 0.0, 0.0)  # identity rotation = Top view
    r3d.lock_rotation = True                  # middle-drag pans instead of orbiting
    r3d.view_location = ((left + right) / 2, (top + bottom) / 2, 0.0)
    r3d.view_distance = max(right - left, top - bottom) * 0.75


def back_to_model(area):
    """Restore this viewport's view from before go_to_refs. False if there's none."""
    saved = _saved_views.pop(area.as_pointer(), None)
    if saved is None:
        return False
    r3d = area.spaces.active.region_3d
    (r3d.view_perspective, r3d.view_location, r3d.view_rotation,
     r3d.view_distance, r3d.lock_rotation) = saved
    return True
