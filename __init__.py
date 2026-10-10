import queue
import threading

import bpy

from . import search

# ---------------------------------------------------------------- #
# Background work: the worker thread and the main-thread timer
# ---------------------------------------------------------------- #

_results = queue.Queue()  # the "counter" where the worker leaves finished work
_worker = None            # the running search thread, if any


def _search_worker(prompt, out):
    """Runs on a background thread. Must never touch bpy."""
    try:
        hits = search.search_wikimedia(prompt)
        out.put(("done", hits))
    except Exception as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def _redraw_sidebars():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _poll_results():
    """Runs on the main thread, every 0.1 s, until the worker reports back."""
    try:
        kind, payload = _results.get_nowait()
    except queue.Empty:
        return 0.1  # nothing yet: check again in 0.1 s

    state = bpy.context.window_manager.assemblage
    state.is_searching = False
    if kind == "error":
        state.status = f"Search failed: {payload}"
    else:
        state.results.clear()
        for hit in payload:
            item = state.results.add()
            item.title = hit["title"].removeprefix("File:")
            item.url = hit["url"]
        state.status = f"{len(payload)} results"
    _redraw_sidebars()
    return None  # returning None stops the timer

# ---------------------------------------------------------------- #
# Properties: where the panel's data lives
# ---------------------------------------------------------------- #

class ASSEMBLAGE_PG_result(bpy.types.PropertyGroup):
    title: bpy.props.StringProperty()
    url: bpy.props.StringProperty()


class ASSEMBLAGE_PG_state(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Subject",
        description="What you're modelling, e.g. 'stage light'",
        default="",
    )
    status: bpy.props.StringProperty(default="")
    is_searching: bpy.props.BoolProperty(default=False)
    results: bpy.props.CollectionProperty(type=ASSEMBLAGE_PG_result)


# ---------------------------------------------------------------- #
# Operator: what the Search button does
# ---------------------------------------------------------------- #

class ASSEMBLAGE_OT_search(bpy.types.Operator):
    bl_idname = "assemblage.search"
    bl_label = "Search"
    bl_description = "Search the web for reference images"

    def execute(self, context):
        global _worker
        state = context.window_manager.assemblage
        prompt = state.prompt.strip()

        if not prompt:
            self.report({'WARNING'}, "Type a subject first")
            return {'CANCELLED'}
        if not bpy.app.online_access:
            self.report({'ERROR'}, "Online access is off. Turn it on in "
                        "Preferences > System > Network > Allow Online Access")
            return {'CANCELLED'}
        if _worker is not None and _worker.is_alive():
            self.report({'WARNING'}, "A search is already running")
            return {'CANCELLED'}

        state.is_searching = True
        state.status = f"Searching for '{prompt}'..."
        # Pass a plain copy of the prompt: the worker can't read Blender data.
        _worker = threading.Thread(target=_search_worker,
                                   args=(prompt, _results), daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


# ---------------------------------------------------------------- #
# Panel: what the sidebar shows
# ---------------------------------------------------------------- #

class ASSEMBLAGE_PT_main(bpy.types.Panel):
    bl_label = "Assemblage"
    bl_idname = "ASSEMBLAGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Assemblage"

    def draw(self, context):
        state = context.window_manager.assemblage
        layout = self.layout
        layout.prop(state, "prompt")

        row = layout.row()
        row.enabled = not state.is_searching  # grey out while searching
        row.operator("assemblage.search", icon='VIEWZOOM')

        if state.status:
            layout.label(text=state.status)
        col = layout.column(align=True)
        for item in state.results:
            col.label(text=item.title)


classes = (
    ASSEMBLAGE_PG_result,  # before state, because state's collection uses it
    ASSEMBLAGE_PG_state,
    ASSEMBLAGE_OT_search,
    ASSEMBLAGE_PT_main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.assemblage = bpy.props.PointerProperty(type=ASSEMBLAGE_PG_state)


def unregister():
    if bpy.app.timers.is_registered(_poll_results):
        bpy.app.timers.unregister(_poll_results)
    del bpy.types.WindowManager.assemblage
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)