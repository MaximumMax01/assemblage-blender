import glob
import os
import queue
import threading

import bpy

from . import download, filters, search

# ---------------------------------------------------------------- #
# Background work: the worker thread and the main-thread timer
# ---------------------------------------------------------------- #

_results = queue.Queue()  # the "counter" where the worker leaves messages
_worker = None            # the running search thread, if any


def _search_worker(prompt, folder, out):
    """Runs on a background thread. Must never touch bpy."""
    try:
        for old in glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")):
            os.remove(old)  # clear the previous search's images

        out.put(("progress", f"Searching for '{prompt}'..."))
        hits = search.search_wikimedia(prompt)

        def report(n, total):
            out.put(("progress", f"Downloading {n}/{total}..."))

        downloaded, failed = download.download_all(hits, folder, on_progress=report)

        out.put(("progress", f"Checking {len(downloaded)} images..."))
        kept, rejected = filters.filter_all(downloaded)
        out.put(("done", (kept, len(failed), len(rejected))))
    except Exception as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def _redraw_sidebars():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _poll_results():
    """Runs on the main thread every 0.1 s. Reads ALL waiting messages."""
    state = bpy.context.window_manager.assemblage
    finished = False

    while True:
        try:
            kind, payload = _results.get_nowait()
        except queue.Empty:
            break  # queue is empty: stop reading for this tick

        if kind == "progress":
            state.status = payload
        elif kind == "error":
            state.status = f"Search failed: {payload}"
            finished = True
        elif kind == "done":
            kept, n_failed, n_rejected = payload
            state.results.clear()
            for hit in kept:
                item = state.results.add()
                item.title = hit["title"].removeprefix("File:")
                item.url = hit["url"]
                item.path = hit["path"]
            state.status = (f"{len(kept)} kept, {n_rejected} filtered out, "
                            f"{n_failed} failed to download")
            finished = True

    _redraw_sidebars()
    if finished:
        state.is_searching = False
        return None  # stop the timer
    return 0.1       # check again in 0.1 s

# ---------------------------------------------------------------- #
# Properties: where the panel's data lives
# ---------------------------------------------------------------- #

class ASSEMBLAGE_PG_result(bpy.types.PropertyGroup):
    title: bpy.props.StringProperty()
    url: bpy.props.StringProperty()
    path: bpy.props.StringProperty()


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
        # The worker can't call bpy, so the main thread looks up the folder
        # and hands over plain strings.
        folder = bpy.utils.extension_path_user(__package__, path="cache", create=True)
        _worker = threading.Thread(target=_search_worker,
                                   args=(prompt, folder, _results), daemon=True)
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