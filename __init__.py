import bpy


class ASSEMBLAGE_PT_main(bpy.types.Panel):
    bl_label = "Assemblage"          # title shown on the panel
    bl_idname = "ASSEMBLAGE_PT_main" # unique ID; "_PT_" marks it as a Panel Type
    bl_space_type = "VIEW_3D"        # lives in the 3D viewport...
    bl_region_type = "UI"            # ...in the N-panel sidebar...
    bl_category = "Assemblage"       # ...under its own tab

    def draw(self, context):
        self.layout.label(text="Hello from Assemblage")


classes = (ASSEMBLAGE_PT_main,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)