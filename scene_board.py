"""Build a reference board inside Blender, in its own scene.

Uses bpy, so MAIN THREAD ONLY. Shares its layout math with the PureRef board.
"""

import os

import bpy
from PIL import Image

from .layout import justified_rows

SCENE_NAME = "Assemblage References"
UNIT = 1 / 1000     # 1000 canvas units = 1 Blender unit, so each row is ~1 m tall
BOARD_SPACING = 0.5  # gap between boards stacked in the same scene


def get_or_create_scene():
    scene = bpy.data.scenes.get(SCENE_NAME)
    if scene is None:
        scene = bpy.data.scenes.new(SCENE_NAME)
    return scene


def _lowest_point(scene):
    """Bottom edge of everything we've placed before, or None for an empty scene."""
    bottoms = [obj["assemblage_bottom"] for obj in scene.objects if "assemblage_bottom" in obj]
    return min(bottoms) if bottoms else None


def build_scene_board(entries, board_name):
    """entries: list of (path, label, source_url). Returns (scene, center, width)."""
    scene = get_or_create_scene()

    aspects = []
    for path, label, url in entries:
        with Image.open(path) as img:  # reads only the header: fast
            w, h = img.size
        aspects.append((w / h, label))
    rects = justified_rows(aspects)

    collection = bpy.data.collections.new(board_name)
    scene.collection.children.link(collection)

    lowest = _lowest_point(scene)
    top = 0.0 if lowest is None else lowest - BOARD_SPACING

    for (path, label, url), (cx, cy, w, h) in zip(entries, rects):
        image = bpy.data.images.load(path, check_existing=True)
        image.pack()  # embed in the .blend: the cache folder gets wiped on the next search

        obj = bpy.data.objects.new(os.path.basename(path), None)  # None = an empty
        obj.empty_display_type = 'IMAGE'
        obj.data = image
        obj.empty_display_size = max(w, h) * UNIT  # the image's longer side
        # Canvas y grows downward; Blender's y grows upward, so flip it.
        obj.location = (cx * UNIT, top - cy * UNIT, 0.0)
        obj["assemblage_source"] = url
        obj["assemblage_bottom"] = top - (cy + h / 2) * UNIT
        collection.objects.link(obj)

    bottom = min(top - (cy + h / 2) * UNIT for (cx, cy, w, h) in rects)
    right = max((cx + w / 2) * UNIT for (cx, cy, w, h) in rects)
    center = (right / 2, (top + bottom) / 2, 0.0)
    return scene, center, max(right, top - bottom)


def frame_top_view(screen, center, size):
    """Point every 3D viewport in this screen straight down at the board."""
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        r3d = area.spaces.active.region_3d
        r3d.view_perspective = 'ORTHO'
        r3d.view_rotation = (1.0, 0.0, 0.0, 0.0)  # identity rotation = Top view
        r3d.view_location = center
        r3d.view_distance = size * 0.75
