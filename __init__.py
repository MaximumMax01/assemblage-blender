import bpy
import time

class ASSEMBLAGE_PG_state(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Subject",
        description="What you're modelling, e.g. 'stage light'",
        default="",
    )


class ASSEMBLAGE_OT_search(bpy.types.Operator):
    bl_idname = "assemblage.search"
    bl_label = "Search"
    bl_description = "Search the web for reference images"

    def execute(self, context):
        prompt = context.window_manager.assemblage.prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "Type a subject first")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Would search for: {prompt}")
        return {'FINISHED'}


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
        layout.operator("assemblage.search", icon='VIEWZOOM')


classes = (ASSEMBLAGE_PG_state, ASSEMBLAGE_OT_search, ASSEMBLAGE_PT_main)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.assemblage = bpy.props.PointerProperty(type=ASSEMBLAGE_PG_state)


def unregister():
    del bpy.types.WindowManager.assemblage
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)