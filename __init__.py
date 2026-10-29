import glob
import os
import queue
import subprocess
import sys
import threading

import bpy
import bpy.utils.previews

from . import board, download, filters, model_store, ranking, scene_board, search

# ---------------------------------------------------------------- #
# Background work: the worker thread and the main-thread timer
# ---------------------------------------------------------------- #

_results = queue.Queue()  # the "counter" where the worker leaves messages
_worker = None            # the running search thread, if any
_previews = None          # thumbnail collection (main thread only)


def _search_worker(prompt, folder, models_dir, auto_pick, out):
    """Runs on a background thread. Must never touch bpy."""
    try:
        for old in glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")):
            os.remove(old)  # clear the previous search's images

        out.put(("progress", f"Searching for '{prompt}'..."))
        hits, problems = search.search_all(prompt)
        if not hits:
            raise RuntimeError("no results" + (f": {'; '.join(problems)}" if problems else ""))

        def report(n, total):
            out.put(("progress", f"Downloading {n}/{total}..."))

        downloaded, failed = download.download_all(hits, folder, on_progress=report)

        out.put(("progress", f"Checking {len(downloaded)} images..."))
        kept, rejected = filters.filter_all(downloaded)

        note = ""
        if auto_pick and kept and model_store.is_installed(models_dir):
            out.put(("progress", f"AI is scoring {len(kept)} images..."))
            try:
                scores = ranking.score(prompt, [hit["path"] for hit in kept], models_dir)
                picks = ranking.choose(scores)
                for i, hit in enumerate(kept):
                    hit["score"] = scores[i]
                    hit["picked"] = i in picks
                kept.sort(key=lambda hit: -hit["score"])  # best first in the picker
                note = f", AI picked {len(picks)}"
            except Exception as exc:
                # Scoring is a bonus: if it breaks, still deliver the images, and say why.
                note = f" (AI scoring failed: {type(exc).__name__}: {exc})"
        if problems:
            note += f" ({'; '.join(problems)})"
        out.put(("done", (kept, len(failed), len(rejected), note)))
    except Exception as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def _model_worker(models_dir, out):
    """Runs on a background thread: downloads and verifies the AI model."""
    try:
        def report(name, received, total):
            mb = received // (1024 * 1024)
            if received % (8 * 1024 * 1024) < model_store.CHUNK:  # about every 8 MB
                total_mb = f"/{total // (1024 * 1024)}" if total else ""
                out.put(("progress", f"Downloading {name}: {mb}{total_mb} MB"))

        model_store.download(models_dir, on_progress=report)
        out.put(("model_done", None))
    except Exception as exc:
        out.put(("error", f"Model download failed: {type(exc).__name__}: {exc}"))


def _models_dir(create=False):
    return bpy.utils.extension_path_user(__package__, path="models", create=create)


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
        elif kind == "model_done":
            state.status = "AI model ready. Auto-pick is on for your next search."
            finished = True
        elif kind == "done":
            kept, n_failed, n_rejected, note = payload
            state.results.clear()
            for hit in kept:
                item = state.results.add()
                item.title = hit["title"].removeprefix("File:")
                item.url = hit["url"]
                item.path = hit["path"]
                item.score = hit.get("score", -1.0)
                item.selected = hit.get("picked", False)
                if item.path not in _previews:  # the same file twice would crash load()
                    _previews.load(item.path, item.path, 'IMAGE')  # key = file path
            state.status = (f"{len(kept)} kept, {n_rejected} filtered out, "
                            f"{n_failed} failed to download{note}")
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
    score: bpy.props.FloatProperty(default=-1.0)  # -1 = not scored
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
    auto_pick: bpy.props.BoolProperty(
        name="Auto-pick",
        description="Let the AI rank the images and tick the best ones for you",
        default=True,
    )


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
                                   args=(prompt, folder, _models_dir(), state.auto_pick, _results),
                                   daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


class ASSEMBLAGE_OT_download_model(bpy.types.Operator):
    bl_idname = "assemblage.download_model"
    bl_label = f"Download AI Model ({model_store.DOWNLOAD_MB} MB)"
    bl_description = "One-time download of the model that ranks and auto-picks images"

    def execute(self, context):
        global _worker
        state = context.window_manager.assemblage
        if not bpy.app.online_access:
            self.report({'ERROR'}, "Online access is off. Turn it on in "
                        "Preferences > System > Network > Allow Online Access")
            return {'CANCELLED'}
        if _worker is not None and _worker.is_alive():
            self.report({'WARNING'}, "Still working on the last task")
            return {'CANCELLED'}
        state.is_searching = True
        state.status = "Starting model download..."
        _worker = threading.Thread(target=_model_worker,
                                   args=(_models_dir(create=True), _results), daemon=True)
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
            scene_board.show_refs(context, bounds)
        self.report({'INFO'}, f"Added {len(entries)} reference images")
        return {'FINISHED'}


class ASSEMBLAGE_OT_show_refs(bpy.types.Operator):
    bl_idname = "assemblage.show_refs"
    bl_label = "Show References"
    bl_description = "Open a side viewport showing your reference boards"

    def execute(self, context):
        collection = bpy.data.collections.get(scene_board.COLLECTION_NAME)
        bounds = scene_board.ref_bounds(collection) if collection else None
        if bounds is None or not _in_viewport(context):
            self.report({'WARNING'}, "No reference boards in this file yet")
            return {'CANCELLED'}
        scene_board.show_refs(context, bounds)
        return {'FINISHED'}


class ASSEMBLAGE_OT_close_refs(bpy.types.Operator):
    bl_idname = "assemblage.close_refs"
    bl_label = "Close References"
    bl_description = "Close the side viewport showing your references"

    def execute(self, context):
        if not scene_board.close_refs(context):
            self.report({'WARNING'}, "The references viewport isn't open")
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

        if scene_board.find_ref_area(context.screen) is not None:
            layout.operator("assemblage.close_refs", icon='PANEL_CLOSE')
        elif bpy.data.collections.get(scene_board.COLLECTION_NAME):
            layout.operator("assemblage.show_refs", icon='IMAGE_REFERENCE')

        row = layout.row()
        row.enabled = not state.is_searching  # grey out while busy
        if model_store.is_installed(_models_dir()):
            row.prop(state, "auto_pick")
        else:
            row.operator("assemblage.download_model", icon='IMPORT')

        row = layout.row()
        row.enabled = not state.is_searching
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
            label = item.title[:20] if item.score < 0 else f"{item.score:.2f}  {item.title[:14]}"
            row.prop(item, "selected", text=label)
            op = row.operator("assemblage.view_image", text="", icon='IMAGE_DATA')
            op.path = item.path


classes = (
    ASSEMBLAGE_PG_result,  # before state, because state's collection uses it
    ASSEMBLAGE_PG_state,
    ASSEMBLAGE_OT_search,
    ASSEMBLAGE_OT_download_model,
    ASSEMBLAGE_OT_view_image,
    ASSEMBLAGE_OT_board_pureref,
    ASSEMBLAGE_OT_board_blender,
    ASSEMBLAGE_OT_show_refs,
    ASSEMBLAGE_OT_close_refs,
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
