import glob
import os
import queue
import subprocess
import sys
import textwrap
import threading

import bpy
import bpy.utils.previews

from . import board, download, filters, model_store, ranking, scene_board, search, terms

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
        elif kept and not model_store.is_installed(models_dir):
            note = ". Tick the ones you want, or get AI Auto-Pick to rank them for you"
        if problems:
            note += f" ({'; '.join(problems)})"
        out.put(("done", (kept, len(failed), len(rejected), note)))
    except Exception as exc:
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def _terms_worker(text, out):
    """Runs on a background thread: asks for trade names. Must never touch bpy."""
    try:
        out.put(("terms", (text, terms.suggest(text))))
    except Exception as exc:
        out.put(("terms_failed", f"{type(exc).__name__}: {exc}"))


def _model_worker(models_dir, out, rescore=None):
    """Runs on a background thread: downloads and verifies the AI model.

    rescore: (prompt, image paths) of the results already on screen, or None.
    If given, they're ranked straight away, so nobody has to search again
    just to see what the AI would have picked.
    """
    try:
        def report(name, received, total):
            mb = received // (1024 * 1024)
            if received % (8 * 1024 * 1024) < model_store.CHUNK:  # about every 8 MB
                total_mb = f"/{total // (1024 * 1024)}" if total else ""
                out.put(("progress", f"Downloading {name}: {mb}{total_mb} MB"))

        model_store.download(models_dir, on_progress=report)
    except Exception as exc:
        out.put(("error", f"Model download failed: {type(exc).__name__}: {exc}"))
        return

    if not rescore:
        out.put(("model_done", ""))
        return
    prompt, paths = rescore
    out.put(("progress", f"AI is scoring {len(paths)} images..."))
    try:
        scores = ranking.score(prompt, paths, models_dir)
        out.put(("rescored", (paths, scores, ranking.choose(scores))))
    except Exception as exc:
        # The download worked; only the bonus step failed. Say so, don't hide it.
        out.put(("model_done", f" Couldn't rank the current images ({type(exc).__name__}: {exc})."))


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
        # run, not Popen: `open` exits at once, and its exit code says whether
        # any app could open the file (Popen would hide that failure).
        result = subprocess.run(["open", path], capture_output=True, timeout=10)
        if result.returncode != 0:
            raise OSError(result.stderr.decode(errors="replace").strip() or "no app can open it")
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
            except (OSError, subprocess.SubprocessError):
                state.status = (f"Board saved as {os.path.basename(payload)}, but it couldn't be "
                                "opened. Is PureRef installed? Get it at pureref.com, or use "
                                "Send to Blender. Opening the folder so you can find the file.")
                try:
                    _open_in_system(os.path.dirname(payload))
                except (OSError, subprocess.SubprocessError):
                    pass  # the message above still says what happened
            finished = True
        elif kind == "terms":
            text, found = payload
            state.suggested_for = text
            state.suggestions.clear()
            for t in found:
                item = state.suggestions.add()
                item.term, item.gloss = t["term"], t["gloss"]
            state.status = "Click the one you mean to search for it"
            finished = True
        elif kind == "terms_failed":
            # Never a dead end: plain Search still works on the user's own words.
            state.status = f"No name suggestions ({payload}). Search uses your words as typed."
            finished = True
        elif kind == "model_done":
            state.status = "AI model ready. Auto-pick is on for your next search." + payload
            finished = True
        elif kind == "rescored":
            paths, scores, picks = payload
            score_of = dict(zip(paths, scores))
            picked = {paths[i] for i in picks}
            # A collection can't be sorted in place, so copy it out, sort, refill.
            # Keep anything the user had already ticked by hand.
            rows = [(item.title, item.url, item.path, item.selected) for item in state.results]
            rows.sort(key=lambda row: -score_of.get(row[2], -1.0))
            state.results.clear()
            for title, url, path, was_selected in rows:
                item = state.results.add()
                item.title, item.url, item.path = title, url, path
                item.score = score_of.get(path, -1.0)
                item.selected = was_selected or path in picked
            state.status = f"AI model ready: ranked these {len(rows)} images and picked {len(picked)}."
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


class ASSEMBLAGE_PG_term(bpy.types.PropertyGroup):
    term: bpy.props.StringProperty()
    gloss: bpy.props.StringProperty()


class ASSEMBLAGE_PG_state(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Subject",
        description="Be specific: colour, material and style all change what gets picked, "
                    "e.g. 'black mesh office chair' rather than 'chair'",
        default="",
    )
    status: bpy.props.StringProperty(default="")
    is_searching: bpy.props.BoolProperty(default=False)
    results: bpy.props.CollectionProperty(type=ASSEMBLAGE_PG_result)
    suggestions: bpy.props.CollectionProperty(type=ASSEMBLAGE_PG_term)
    suggested_for: bpy.props.StringProperty(default="")
    last_search: bpy.props.StringProperty(default="")  # what the current results came from
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
        state.last_search = prompt
        # The worker can't call bpy, so the main thread looks up the folder
        # and hands over plain strings.
        folder = bpy.utils.extension_path_user(__package__, path="cache", create=True)
        _worker = threading.Thread(target=_search_worker,
                                   args=(prompt, folder, _models_dir(), state.auto_pick, _results),
                                   daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


class ASSEMBLAGE_OT_suggest(bpy.types.Operator):
    bl_idname = "assemblage.suggest"
    bl_label = "Suggest Names"
    bl_description = ("Don't know what it's called? Describe it in plain words and get the "
                      "names used on product pages (sends your description to Assemblage's server)")

    def execute(self, context):
        global _worker
        state = context.window_manager.assemblage
        text = state.prompt.strip()
        if not text:
            self.report({'WARNING'}, "Describe the thing first, e.g. 'rubber strip where office walls meet the floor'")
            return {'CANCELLED'}
        if not bpy.app.online_access:
            self.report({'ERROR'}, "Online access is off. Turn it on in "
                        "Preferences > System > Network > Allow Online Access")
            return {'CANCELLED'}
        if _worker is not None and _worker.is_alive():
            self.report({'WARNING'}, "Still working on the last task")
            return {'CANCELLED'}
        state.is_searching = True
        state.status = "Finding the right names..."
        _worker = threading.Thread(target=_terms_worker, args=(text, _results), daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


class ASSEMBLAGE_OT_use_term(bpy.types.Operator):
    bl_idname = "assemblage.use_term"
    bl_label = "Use Name"
    bl_description = "Search for this name"

    term: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    gloss: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return properties.gloss or cls.bl_description

    def execute(self, context):
        # The name becomes the prompt, so the web search AND the CLIP ranking
        # both use it. Ranking by the old words would favour the wrong images.
        context.window_manager.assemblage.prompt = self.term
        return bpy.ops.assemblage.search()


class ASSEMBLAGE_OT_download_model(bpy.types.Operator):
    bl_idname = "assemblage.download_model"
    bl_label = f"Get AI Auto-Pick ({model_store.DOWNLOAD_MB} MB, one time)"
    bl_description = ("Downloads the AI that ranks results and ticks the best ones. "
                      "Searching works without it")

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
        rescore = None
        if state.results and state.auto_pick:
            rescore = (state.last_search or state.prompt, [item.path for item in state.results])
        _worker = threading.Thread(target=_model_worker,
                                   args=(_models_dir(create=True), _results, rescore), daemon=True)
        _worker.start()
        bpy.app.timers.register(_poll_results, first_interval=0.1)
        return {'FINISHED'}


class ASSEMBLAGE_OT_open_network_prefs(bpy.types.Operator):
    bl_idname = "assemblage.open_network_prefs"
    bl_label = "Open Network Settings"
    bl_description = "Open Preferences at System, where 'Allow Online Access' is (under Network)"

    def execute(self, context):
        # Only opens the window: turning internet access on is the user's choice.
        bpy.ops.screen.userpref_show(section='SYSTEM')
        self.report({'INFO'}, "Tick 'Allow Online Access' under Network, then come back")
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

# Target thumbnail width for each size, in Blender "UI units". One unit is
# 20 px at 100% interface scale and grows with the user's scale setting, so
# sizes look the same on a laptop and on a big monitor.
THUMB_UNITS = {"SMALL": 6.0, "MEDIUM": 9.0, "LARGE": 13.0}


class ASSEMBLAGE_AP_prefs(bpy.types.AddonPreferences):
    """Settings Blender saves between sessions (Preferences > Add-ons)."""
    bl_idname = __package__

    thumb_size: bpy.props.EnumProperty(
        name="Thumbnail Size",
        items=[("SMALL", "S", "Small thumbnails, more per row"),
               ("MEDIUM", "M", "Medium thumbnails"),
               ("LARGE", "L", "Large thumbnails, fewer per row")],
        default="MEDIUM",
    )

    def draw(self, context):
        self.layout.prop(self, "thumb_size", expand=True)


def _prefs(context):
    """This add-on's saved preferences, or None if Blender can't find them."""
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


class _AssemblagePanel:
    """Settings every Assemblage panel shares: the N-sidebar's Assemblage tab."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Assemblage"


def _wrapped_label(layout, context, text, max_lines=3):
    """Blender labels never wrap, so split long text across several labels.

    Width is an estimate: about 7 px per character at 100% UI scale, minus
    some padding for the panel and box edges.
    """
    px_per_char = 7 * context.preferences.system.ui_scale
    chars = max(16, int((context.region.width - 40) / px_per_char))
    lines = textwrap.wrap(text, width=chars) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    col = layout.column(align=True)
    col.scale_y = 0.8  # tighter line spacing than separate labels normally get
    for line in lines:
        col.label(text=line)


def _short(text, limit):
    """Cut long text at `limit` characters and say so with an ellipsis."""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class ASSEMBLAGE_PT_main(_AssemblagePanel, bpy.types.Panel):
    bl_label = "Assemblage"
    bl_idname = "ASSEMBLAGE_PT_main"

    def draw(self, context):
        state = context.window_manager.assemblage
        layout = self.layout
        if not bpy.app.online_access:
            # Blender ships with internet access off. Say so before the first
            # click fails, and put the setting one click away.
            box = layout.box()
            _wrapped_label(box, context, "Assemblage needs internet access to search. "
                                         "Blender keeps it off until you allow it.")
            box.operator("assemblage.open_network_prefs", icon='PREFERENCES')
        layout.prop(state, "prompt")
        if len(state.prompt.split()) < 2:  # vanishes once the prompt gets specific
            _wrapped_label(layout, context,
                "Tip: be specific, and say where if it matters, "
                "e.g. 'drinking fountain on a hallway wall'")

        busy = layout.column()
        busy.enabled = not state.is_searching  # grey out everything in here while busy
        row = busy.row(align=True)
        row.scale_y = 1.3 # the two main actions get bigger buttons
        row.operator("assemblage.suggest", icon='QUESTION')
        row.operator("assemblage.search", icon='VIEWZOOM')
        if model_store.is_installed(_models_dir()):
            busy.prop(state, "auto_pick")
        else:
            busy.operator("assemblage.download_model", icon='IMPORT')

        if state.status:
            _wrapped_label(layout, context, state.status, max_lines=5)

        if scene_board.find_ref_area(context.screen) is not None:
            layout.operator("assemblage.close_refs", icon='PANEL_CLOSE')
        elif bpy.data.collections.get(scene_board.COLLECTION_NAME):
            layout.operator("assemblage.show_refs", icon='IMAGE_REFERENCE')


class ASSEMBLAGE_PT_suggestions(_AssemblagePanel, bpy.types.Panel):
    bl_label = "Suggested Names"
    bl_idname = "ASSEMBLAGE_PT_suggestions"
    bl_parent_id = "ASSEMBLAGE_PT_main"  # makes this a collapsible sub-panel

    @classmethod
    def poll(cls, context):
        # Returning False hides the whole sub-panel until there's something to show.
        return len(context.window_manager.assemblage.suggestions) > 0

    def draw(self, context):
        state = context.window_manager.assemblage
        layout = self.layout
        row = layout.row()
        row.active = False  # dims the text without disabling anything: a caption look
        row.label(text=f"For '{_short(state.suggested_for, 40)}'")

        for s in state.suggestions:
            box = layout.box()
            box.enabled = not state.is_searching
            if s.gloss:
                _wrapped_label(box, context, s.gloss)  # what it is, above its name
            op = box.operator("assemblage.use_term", text=s.term,
                              depress=(s.term == state.prompt))  # pressed = searched now
            op.term, op.gloss = s.term, s.gloss


class ASSEMBLAGE_PT_results(_AssemblagePanel, bpy.types.Panel):
    bl_label = "Results"
    bl_idname = "ASSEMBLAGE_PT_results"
    bl_parent_id = "ASSEMBLAGE_PT_main"

    @classmethod
    def poll(cls, context):
        return len(context.window_manager.assemblage.results) > 0

    def draw_header_preset(self, context):
        # Drawn at the right end of the header, so it shows even when collapsed.
        state = context.window_manager.assemblage
        n_selected = sum(item.selected for item in state.results)
        self.layout.label(text=f"{n_selected} of {len(state.results)} picked")

    def draw(self, context):
        state = context.window_manager.assemblage
        layout = self.layout
        n_selected = sum(item.selected for item in state.results)

        row = layout.row(align=True)
        row.enabled = n_selected > 0 and not state.is_searching
        row.operator("assemblage.board_pureref", icon='EXPORT')
        row.operator("assemblage.board_blender", icon='IMAGE_REFERENCE')

        prefs = _prefs(context)
        size = prefs.thumb_size if prefs else "MEDIUM"
        if prefs:
            split = layout.split(factor=0.35)
            split.label(text="Thumbnails")
            split.row(align=True).prop(prefs, "thumb_size", expand=True)

        # Fit as many columns as the chosen size allows, then stretch the
        # thumbnails to fill the row exactly. Widen the sidebar: more columns.
        unit_px = 20 * context.preferences.system.ui_scale
        avail = max(4.0, (context.region.width - 30) / unit_px)  # minus scrollbar/margins
        columns = max(1, int(avail // THUMB_UNITS[size]))
        cell = avail / columns
        icon_scale = cell - 1.2              # room for the card border and gap
        title_chars = max(6, int(cell * 20 / 7) - 6)  # ~7 px per letter, minus the button

        # row_major: fill left to right, then down, so the best results read first
        grid = layout.grid_flow(row_major=True, columns=columns, even_columns=True,
                                even_rows=False, align=False)
        for item in state.results:
            card = grid.box().column(align=True)
            preview = _previews.get(item.path)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=icon_scale)
            else:
                card.label(text="No preview", icon='IMAGE')
            row = card.row(align=True)
            # A toggle button instead of a tiny checkbox: the whole bar lights up when picked.
            row.prop(item, "selected", toggle=True,
                     text=_short(item.title or "Untitled", title_chars),
                     icon='CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT')
            op = row.operator("assemblage.view_image", text="", icon='FULLSCREEN_ENTER')
            op.path = item.path


classes = (
    ASSEMBLAGE_AP_prefs,
    ASSEMBLAGE_PG_result,  # before state, because state's collection uses it
    ASSEMBLAGE_PG_term,
    ASSEMBLAGE_PG_state,
    ASSEMBLAGE_OT_search,
    ASSEMBLAGE_OT_suggest,
    ASSEMBLAGE_OT_use_term,
    ASSEMBLAGE_OT_download_model,
    ASSEMBLAGE_OT_open_network_prefs,
    ASSEMBLAGE_OT_view_image,
    ASSEMBLAGE_OT_board_pureref,
    ASSEMBLAGE_OT_board_blender,
    ASSEMBLAGE_OT_show_refs,
    ASSEMBLAGE_OT_close_refs,
    ASSEMBLAGE_PT_main,         # parents before their sub-panels
    ASSEMBLAGE_PT_suggestions,
    ASSEMBLAGE_PT_results,
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
