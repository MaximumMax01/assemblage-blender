import glob
import os
import queue
import subprocess
import sys
import threading

import bpy
import bpy.utils.previews

from . import board, download, filters, scene_board, search

# ---------------------------------------------------------------- #
# Background work: the worker thread and the main-thread timer
# ---------------------------------------------------------------- #

_results = queue.Queue()  # the "counter" where the worker leaves messages
_worker = None            # the running search thread, if any
_previews = None          # thumbnail collection (main thread only)


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


def _board_worker(entries, output_path, out):
    """Runs on a background thread: writes the .pur file. Must never touch bpy."""
    try:
        board.build_board(entries, output_path)
        out.put(("board_done", output_path))
    except Exception as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def _open_in_system(path):
    """Open a file with the operating system's default app for its type."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


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
            state.status = f"Failed: {payload}"
            finished = True
        elif kind == "board_done":
            state.status = f"Board saved: {os.path.basename(payload)}"
            try:
                _open_in_system(payload)
            except OSError as exc:
                state.status = f"Board saved, but couldn't open PureRef: {exc}"
            finished = True
        elif kind == "done":
            kept, n_failed, n_rejected = payload
            state.results.clear()
            for hit in kept:
                item = state.results.add()
                item.title = hit["title"].removeprefix("File:")
                item.url = hit["url"]
                item.path = hit["path"]
                _previews.load(item.path, item.path, 'IMAGE')  # key = file path
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
    selected: bpy.props.BoolProperty(name="Use", default=False)


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

        # Let go of the old thumbnails BEFORE the worker deletes their files.
        state.results.clear()
        _previews.clear()

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


class ASSEMBLAGE_OT_view_image(bpy.types.Operator):
    bl_idname = "assemblage.view_image"
    bl_label = "View Image"
    bl_description = "Open this image full size in your system's image viewer"

    path: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        cache = os.path.abspath(bpy.utils.extension_path_user(__package__, path="cache"))
        path = os.path.abspath(self.path)
        # Only open our own downloaded images, never an arbitrary file.
        inside_cache = os.path.commonpath([path, cache]) == cache
        if not (inside_cache and path.lower().endswith((".jpg", ".png")) and os.path.isfile(path)):
            self.report({'ERROR'}, "Can only open downloaded reference images")
            return {'CANCELLED'}
        try:
            _open_in_system(path)
        except OSError as exc:
            self.report({'ERROR'}, f"Couldn't open image: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


def _selected_entries(state):
    """(path, label, url) for every ticked image, in picker order."""
    return [(item.path, "picks", item.url) for item in state.results if item.selected]


def _safe_filename(text):
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in text).strip()
    return (cleaned or "board").replace(" ", "_")[:60]


class ASSEMBLAGE_OT_board_pureref(bpy.types.Operator):
    bl_idname = "assemblage.board_pureref"
    bl_label = "Send to PureRef"
    bl_description = "Save the selected images as a PureRef board and open it"

    def execute(self, context):
        global _worker
        state = context.window_manager.assemblage
        entries = _selected_entries(state)
        if not entries:
            self.report({'WARNING'}, "Tick at least one image first")
            return {'CANCELLED'}
        if _worker is not None and _worker.is_alive():
            self.report({'WARNING'}, "Still working on the last task")
            return {'CANCELLED'}

        # Next to the .blend if it's been saved; otherwise in our own folder.
        if bpy.data.filepath:
            folder = os.path.dirname(bpy.data.filepath)
        else:
            folder = bpy.utils.extension_path_user(__package__, path="boards", create=True)
        output_path = os.path.join(folder, _safe_filename(state.prompt) + ".pur")

        state.is_searching = True
        state.status = f"Writing board with {len(entries)} images..."
        _worker = threading.Thread(target=_board_worker,
                                   args=(entries, output_path, _results), daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


def _in_viewport(context):
    return context.area is not None and context.area.type == 'VIEW_3D'


class ASSEMBLAGE_OT_board_blender(bpy.types.Operator):
    bl_idname = "assemblage.board_blender"
    bl_label = "Send to Blender"
    bl_description = "Lay out the selected images as references, far from your model"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = context.window_manager.assemblage
        entries = _selected_entries(state)
        if not entries:
            self.report({'WARNING'}, "Tick at least one image first")
            return {'CANCELLED'}

        bounds = scene_board.build_scene_board(
            context.scene, entries, state.prompt.strip() or "References")
        if _in_viewport(context):
            scene_board.go_to_refs(context.area, bounds)
        self.report({'INFO'}, f"Added {len(entries)} reference images")
        return {'FINISHED'}


class ASSEMBLAGE_OT_go_to_refs(bpy.types.Operator):
    bl_idname = "assemblage.go_to_refs"
    bl_label = "Go to References"
    bl_description = "Point this viewport at your reference boards"

    def execute(self, context):
        collection = bpy.data.collections.get(scene_board.COLLECTION_NAME)
        bounds = scene_board.ref_bounds(collection) if collection else None
        if bounds is None or not _in_viewport(context):
            self.report({'WARNING'}, "No reference boards in this file yet")
            return {'CANCELLED'}
        scene_board.go_to_refs(context.area, bounds)
        return {'FINISHED'}


class ASSEMBLAGE_OT_back_to_model(bpy.types.Operator):
    bl_idname = "assemblage.back_to_model"
    bl_label = "Back to Model"
    bl_description = "Return this viewport to where it was"

    def execute(self, context):
        if not (_in_viewport(context) and scene_board.back_to_model(context.area)):
            self.report({'WARNING'}, "Nothing to go back to")
            return {'CANCELLED'}
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

        if context.area is not None and scene_board.is_at_refs(context.area):
            layout.operator("assemblage.back_to_model", icon='LOOP_BACK')
        elif bpy.data.collections.get(scene_board.COLLECTION_NAME):
            layout.operator("assemblage.go_to_refs", icon='IMAGE_REFERENCE')

        row = layout.row()
        row.enabled = not state.is_searching  # grey out while busy
        row.operator("assemblage.search", icon='VIEWZOOM')

        if state.status:
            layout.label(text=state.status)
        if not state.results:
            return

        n_selected = sum(item.selected for item in state.results)
        layout.label(text=f"{n_selected} of {len(state.results)} selected")

        row = layout.row(align=True)
        row.enabled = n_selected > 0 and not state.is_searching
        row.operator("assemblage.board_pureref", icon='EXPORT')
        row.operator("assemblage.board_blender", icon='IMAGE_REFERENCE')

        grid = layout.grid_flow(columns=2, even_columns=True, align=False)
        for item in state.results:
            cell = grid.column(align=True)
            preview = _previews.get(item.path)
            if preview is not None:
                cell.template_icon(icon_value=preview.icon_id, scale=6.0)
            row = cell.row(align=True)
            row.prop(item, "selected", text=item.title[:20])
            op = row.operator("assemblage.view_image", text="", icon='IMAGE_DATA')
            op.path = item.path


classes = (
    ASSEMBLAGE_PG_result,  # before state, because state's collection uses it
    ASSEMBLAGE_PG_state,
    ASSEMBLAGE_OT_search,
    ASSEMBLAGE_OT_view_image,
    ASSEMBLAGE_OT_board_pureref,
    ASSEMBLAGE_OT_board_blender,
    ASSEMBLAGE_OT_go_to_refs,
    ASSEMBLAGE_OT_back_to_model,
    ASSEMBLAGE_PT_main,
)


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.assemblage = bpy.props.PointerProperty(type=ASSEMBLAGE_PG_state)


def unregister():
    global _previews
    if bpy.app.timers.is_registered(_poll_results):
        bpy.app.timers.unregister(_poll_results)
    del bpy.types.WindowManager.assemblage
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.previews.remove(_previews)
    _previews = None
