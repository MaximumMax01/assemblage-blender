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

REF_VIEW_SHARE = 0.35       # the references viewport takes 35% of the split

# The address of the viewport we split off for references, so we can find it
# again (to reuse or close it) instead of splitting a new one every time.
_ref_area_pointer = None


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


def find_ref_area(screen):
    """The references viewport in this screen, or None if it's been closed."""
    for area in screen.areas:
        if area.as_pointer() == _ref_area_pointer:
            return area
    return None


def _split_off_ref_area(context, main_area):
    """Split main_area side by side and return the new, narrower half."""
    global _ref_area_pointer
    before = {a.as_pointer() for a in context.screen.areas}
    region = next(r for r in main_area.regions if r.type == 'WINDOW')
    # Operators act on "the current area", so we temporarily tell Blender
    # which area that is. This is called a context override.
    with context.temp_override(area=main_area, region=region):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=1 - REF_VIEW_SHARE)
    halves = [a for a in context.screen.areas
              if a.as_pointer() not in before or a.as_pointer() == main_area.as_pointer()]
    ref_area = min(halves, key=lambda a: a.width)  # whichever half came out narrower
    _ref_area_pointer = ref_area.as_pointer()
    return ref_area


def _hide_everything_but_images(space):
    """Strip the references viewport down to just the pictures."""
    o = space.overlay
    o.show_floor = False            # the grid floor in perspective views
    o.show_ortho_grid = False       # the grid in top/front/side views
    o.show_axis_x = o.show_axis_y = o.show_axis_z = False  # red/green/blue axis lines
    o.show_cursor = False           # the 3D cursor
    o.show_text = False             # "Top Orthographic" label in the corner
    o.show_stats = False
    o.show_object_origins = False   # the dot at each object's center
    o.show_relationship_lines = False
    space.show_gizmo = False        # the navigation gizmo (axis ball, zoom/pan buttons)
    space.show_region_toolbar = False   # left toolbar
    space.show_region_ui = False        # N-panel sidebar


def show_refs(context, bounds):
    """Open (or reuse) a side viewport aimed straight down at the references."""
    area = find_ref_area(context.screen)
    if area is None:
        area = _split_off_ref_area(context, context.area)
        _hide_everything_but_images(area.spaces.active)

    left, top, right, bottom = bounds
    r3d = area.spaces.active.region_3d
    r3d.view_perspective = 'ORTHO'
    r3d.view_rotation = (1.0, 0.0, 0.0, 0.0)  # identity rotation = Top view
    r3d.lock_rotation = True                  # middle-drag pans instead of orbiting
    r3d.view_location = ((left + right) / 2, (top + bottom) / 2, 0.0)
    r3d.view_distance = max(right - left, top - bottom) * 0.75


def close_refs(context):
    """Close the references viewport. False if it isn't open."""
    global _ref_area_pointer
    area = find_ref_area(context.screen)
    if area is None:
        return False
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with context.temp_override(area=area, region=region):
        bpy.ops.screen.area_close()
    _ref_area_pointer = None
    return True
