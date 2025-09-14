bl_info = {
    "name": "Vertex Group Renamer",
    "blender": (2, 80, 0),
    "category": "Object",
    "version": (1, 3, 3),
    "author": "Xenthos",
    "description": "Rename vertex groups and armature bones based on mesh name prefixes with merging and synchronization capabilities",
    "location": "View3D > Tool Shelf > Vertex Group Renamer",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "support": "COMMUNITY"
}

import bpy
import json
import os
import copy

# Global variables for presets and UI states
presets = {}
prefix_expand_states = {}

# Define the path for the preset file
PRESET_FILE_PATH = os.path.join(bpy.utils.resource_path('USER'), "vertex_group_presets.json")

# ============================
# Preset Management Functions
# ============================

def load_presets():
    try:
        if os.path.exists(PRESET_FILE_PATH):
            with open(PRESET_FILE_PATH, 'r') as f:
                print(f"Loading presets from {PRESET_FILE_PATH}")
                return json.load(f)
    except Exception as e:
        print(f"Failed to load presets: {e}")
    return {}

def save_presets(presets):
    try:
        with open(PRESET_FILE_PATH, 'w') as f:
            json.dump(presets, f, indent=4)
        print(f"Presets saved to {PRESET_FILE_PATH}")
    except Exception as e:
        print(f"Failed to save presets: {e}")

def update_preset_dropdown(context):
    # Force a UI redraw
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()

def initialize_presets(context):
    global presets
    presets = load_presets()
    if not presets:
        presets["Default"] = {}

    # Initialize prefix expand states
    current_preset = context.scene.vgr_props.current_preset
    if current_preset not in presets:
        context.scene.vgr_props.current_preset = "Default"
        current_preset = "Default"

    for prefix in presets.get(current_preset, {}):
        if prefix not in prefix_expand_states:
            prefix_expand_states[prefix] = False

    # Register dynamic properties
    register_dynamic_properties(context)

def rename_key_in_ordered_dict(d, old_key, new_key):
    new_dict = {}
    for k in d:
        if k == old_key:
            new_dict[new_key] = d[k]
        else:
            new_dict[k] = d[k]
    return new_dict

# ============================
# Property Definitions
# ============================

def preset_update(self, context):
    preset_name = self.preset_dropdown
    self.current_preset = preset_name
    set_current_preset(context, preset_name)

class VertexGroupRenamerProperties(bpy.types.PropertyGroup):
    preset_dropdown = bpy.props.StringProperty(
        name="Presets",
        description="Choose a preset for renaming rules",
        default='Default',
        update=preset_update,
    )
    current_preset = bpy.props.StringProperty(
        name="Current Preset",
        default='Default',
    )
    sync_group_bone = bpy.props.BoolProperty(
        name="Sync Group and Bone Renaming",
        description="Synchronize renaming between vertex groups and armature bones",
        default=False,
    )

def set_current_preset(context, preset_name):
    global prefix_expand_states
    # Update the scene property
    context.scene.vgr_props.current_preset = preset_name
    # Initialize prefix expand states
    prefix_expand_states.clear()
    for prefix in presets.get(preset_name, {}):
        prefix_expand_states[prefix] = False
    # Register dynamic properties for the current preset
    register_dynamic_properties(context)

def sanitize_property_name(name):
    # Replace invalid characters in property names
    return name.replace(".", "_").replace(" ", "_").replace("-", "_")

def register_dynamic_properties(context):
    # Clear any previously registered properties
    unregister_dynamic_properties()

    current_preset = context.scene.vgr_props.current_preset
    current_rules = presets.get(current_preset, {})

    for prefix, rule_set in current_rules.items():
        for original, new in rule_set.items():
            # Create property names
            original_prop = f"rule_edit_original_{sanitize_property_name(current_preset)}_{sanitize_property_name(prefix)}_{sanitize_property_name(original)}"
            new_prop = f"rule_edit_new_{sanitize_property_name(current_preset)}_{sanitize_property_name(prefix)}_{sanitize_property_name(original)}"

            # Define update functions for the renaming rules
            def make_rule_update_func(prefix, original, new, original_prop, new_prop):
                def update_rule(self, context):
                    new_original = getattr(self, original_prop)
                    new_new = getattr(self, new_prop)

                    if new_original != original or new_new != new:
                        # Check for duplicates
                        if new_original in presets[current_preset][prefix] and new_original != original:
                            self.report({'WARNING'}, f"Rule '{new_original}' already exists in prefix '{prefix}'.")
                            setattr(self, original_prop, original)
                            setattr(self, new_prop, new)
                            return
                        # Update the presets dictionary directly
                        # Preserve the order of rules
                        presets[current_preset][prefix] = rename_key_in_ordered_dict(presets[current_preset][prefix], original, new_original)
                        presets[current_preset][prefix][new_original] = new_new
                        # Save presets
                        save_presets(presets)
                        # Re-register dynamic properties
                        register_dynamic_properties(context)
                        # Force UI update
                        context.area.tag_redraw()
                return update_rule

            # Register properties for each original and new rule name with update callbacks
            setattr(bpy.types.Scene, original_prop, bpy.props.StringProperty(
                name="Old",
                default=original,
                update=make_rule_update_func(prefix, original, new, original_prop, new_prop)
            ))
            setattr(bpy.types.Scene, new_prop, bpy.props.StringProperty(
                name="New",
                default=new,
                update=make_rule_update_func(prefix, original, new, original_prop, new_prop)
            ))

def unregister_dynamic_properties():
    # Unregister all dynamically created properties
    for prop in list(dir(bpy.types.Scene)):
        if prop.startswith("rule_edit_"):
            try:
                delattr(bpy.types.Scene, prop)
            except AttributeError:
                pass

# ============================
# Helper Functions
# ============================

def get_armatures_from_meshes(meshes):
    """
    For each mesh, find the armature in its modifiers.
    Returns a dictionary mapping meshes to their linked armatures.
    """
    mesh_to_armature = {}
    for mesh in meshes:
        armatures = []
        for mod in mesh.modifiers:
            if mod.type == 'ARMATURE' and mod.object and mod.object.type == 'ARMATURE':
                armatures.append(mod.object)
        if len(armatures) > 1:
            mesh_to_armature[mesh] = armatures
        elif len(armatures) == 1:
            mesh_to_armature[mesh] = armatures[0]
    return mesh_to_armature

def get_meshes_from_armatures(armatures):
    """
    For each armature, find the meshes that have it in their modifiers.
    Returns a dictionary mapping armatures to their linked meshes.
    """
    armature_to_meshes = {}
    for armature in armatures:
        meshes = []
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                for mod in obj.modifiers:
                    if mod.type == 'ARMATURE' and mod.object == armature:
                        meshes.append(obj)
        if meshes:
            armature_to_meshes[armature] = meshes
    return armature_to_meshes

# ============================
# Merge and Mirror Functions
# ============================

def merge_vertex_groups(obj, target_group_name, source_group_names):
    """
    Merges multiple vertex groups into one with the target name.
    After merging, normalizes all vertex weights across all groups to ensure no vertex exceeds a total weight of 1.0.
    """
    if not source_group_names:
        return

    # Create a temporary group name to avoid naming conflicts
    temp_group_name = f"__temp_merge_{target_group_name}__"

    # Create the temporary vertex group
    temp_group = obj.vertex_groups.new(name=temp_group_name)

    # Dictionary to store summed weights per vertex
    vertex_weight_sum = {}

    # Iterate through source groups and accumulate weights
    for group_name in source_group_names:
        group = obj.vertex_groups.get(group_name)
        if group is None:
            continue
        for v in obj.data.vertices:
            try:
                weight = group.weight(v.index)
            except RuntimeError:
                weight = 0.0
            if v.index in vertex_weight_sum:
                vertex_weight_sum[v.index] += weight
            else:
                vertex_weight_sum[v.index] = weight

    # Assign summed weights to the temporary group
    for v_index, weight in vertex_weight_sum.items():
        temp_group.add([v_index], weight, 'ADD')

    # Remove the source groups
    for group_name in source_group_names:
        group = obj.vertex_groups.get(group_name)
        if group:
            obj.vertex_groups.remove(group)

    # Rename the temporary group to the target name
    temp_group.name = target_group_name

    # ============================
    # Normalization Step
    # ============================

    # Iterate through all vertices to normalize weights across all vertex groups
    for v in obj.data.vertices:
        total_weight = 0.0
        vertex_groups = obj.vertex_groups
        current_weights = {}

        # Accumulate current weights and store them
        for vg in vertex_groups:
            try:
                weight = vg.weight(v.index)
                current_weights[vg] = weight
                total_weight += weight
            except RuntimeError:
                # Vertex does not have this group; weight is implicitly 0.0
                current_weights[vg] = 0.0

        # If total weight exceeds 1.0, normalize all weights
        if total_weight > 1.0:
            for vg, weight in current_weights.items():
                normalized_weight = weight / total_weight
                vg.add([v.index], normalized_weight, 'REPLACE')

def merge_bones(armature, target_bone_name, source_bone_names):
    """
    Merge multiple bones into one with the target name.
    """
    if not source_bone_names:
        return

    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = armature.data.edit_bones

    # Create a temporary bone
    temp_bone_name = f"__temp_merge_{target_bone_name}__"
    temp_bone = edit_bones.new(temp_bone_name)

    # Position the temporary bone based on the first source bone
    first_bone = edit_bones.get(source_bone_names[0])
    if first_bone:
        temp_bone.head = first_bone.head.copy()
        temp_bone.tail = first_bone.tail.copy()
        temp_bone.roll = first_bone.roll

    # Remove source bones
    for bone_name in source_bone_names:
        bone = edit_bones.get(bone_name)
        if bone:
            edit_bones.remove(bone, do_unlink=True)

    # Rename temporary bone to target name
    temp_bone.name = target_bone_name

    bpy.ops.object.mode_set(mode='OBJECT')

def mirror_names(obj, is_bone=True):
    """
    Mirror names by swapping L_ and R_ prefixes.
    """
    if is_bone:
        target = obj.data.bones
    else:
        target = obj.vertex_groups

    names = [bone.name for bone in target]
    name_swap_pairs = []

    # Build a list of pairs to swap
    for name in names:
        if name.startswith('L_'):
            counterpart = 'R_' + name[2:]
            if counterpart in names:
                name_swap_pairs.append((name, counterpart))
        elif name.startswith('R_'):
            counterpart = 'L_' + name[2:]
            if counterpart in names:
                name_swap_pairs.append((name, counterpart))

    # Perform the swapping using temporary names to avoid conflicts
    for name1, name2 in name_swap_pairs:
        temp_name = '__swap_temp__' + name2
        bone_or_vg = target.get(name1)
        if bone_or_vg:
            bone_or_vg.name = temp_name

    for name1, name2 in name_swap_pairs:
        bone_or_vg = target.get(name2)
        if bone_or_vg:
            bone_or_vg.name = name1

    for name1, name2 in name_swap_pairs:
        temp_name = '__swap_temp__' + name2
        bone_or_vg = target.get(temp_name)
        if bone_or_vg:
            bone_or_vg.name = name2

# ============================
# Operator Definitions
# ============================

class OBJECT_OT_toggle_expand_prefix(bpy.types.Operator):
    """Expand or collapse ruleset to view or hide rules"""
    bl_idname = "object.toggle_expand_prefix"
    bl_label = "Expand/Collapse Ruleset"

    prefix = bpy.props.StringProperty()

    def execute(self, context):
        current_state = prefix_expand_states.get(self.prefix, False)
        prefix_expand_states[self.prefix] = not current_state
        return {'FINISHED'}

class OBJECT_OT_remove_prefix(bpy.types.Operator):
    """Remove ruleset and its associated renaming rules"""
    bl_idname = "object.remove_prefix"
    bl_label = "Remove Ruleset"

    prefix = bpy.props.StringProperty()

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        if self.prefix in presets[current_preset]:
            del presets[current_preset][self.prefix]
            save_presets(presets)
            initialize_presets(context)
            self.report({'INFO'}, f"Prefix '{self.prefix}' removed.")
        else:
            self.report({'WARNING'}, f"Prefix '{self.prefix}' not found.")
        return {'FINISHED'}

class OBJECT_OT_rename_prefix(bpy.types.Operator):
    """Rename ruleset's associated prefix for target meshes/armatures"""
    bl_idname = "object.rename_prefix"
    bl_label = "Rename Ruleset Prefix"

    prefix = bpy.props.StringProperty()

    new_prefix = bpy.props.StringProperty(name="New Prefix")

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_prefix")

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        if self.new_prefix in presets[current_preset]:
            self.report({'ERROR'}, f"Prefix '{self.new_prefix}' already exists.")
            return {'CANCELLED'}
        if self.prefix in presets[current_preset]:
            presets[current_preset][self.new_prefix] = presets[current_preset].pop(self.prefix)
            save_presets(presets)
            initialize_presets(context)
            self.report({'INFO'}, f"Prefix '{self.prefix}' renamed to '{self.new_prefix}'.")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"Prefix '{self.prefix}' not found.")
            return {'CANCELLED'}

class OBJECT_OT_remove_rule(bpy.types.Operator):
    """Remove a renaming rule"""
    bl_idname = "object.remove_rule"
    bl_label = "Remove Rule"

    prefix = bpy.props.StringProperty()
    original_name = bpy.props.StringProperty()

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        if self.prefix in presets[current_preset]:
            if self.original_name in presets[current_preset][self.prefix]:
                del presets[current_preset][self.prefix][self.original_name]
                save_presets(presets)
                initialize_presets(context)
                self.report({'INFO'}, f"Rule '{self.original_name}' removed from prefix '{self.prefix}'.")
            else:
                self.report({'WARNING'}, f"Rule '{self.original_name}' not found in prefix '{self.prefix}'.")
        else:
            self.report({'WARNING'}, f"Prefix '{self.prefix}' not found.")
        return {'FINISHED'}

class OBJECT_OT_add_rule(bpy.types.Operator):
    """Add a new renaming rule to a ruleset"""
    bl_idname = "object.add_rule"
    bl_label = "Add New Rule"

    prefix = bpy.props.StringProperty()

    original_name = bpy.props.StringProperty(name="Old Name")
    new_name = bpy.props.StringProperty(name="New Name")

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "original_name")
        layout.prop(self, "new_name")

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        if not self.original_name or not self.new_name:
            self.report({'ERROR'}, "Both Old and New names must be provided.")
            return {'CANCELLED'}
        if self.original_name in presets[current_preset][self.prefix]:
            self.report({'ERROR'}, f"Rule '{self.original_name}' already exists in prefix '{self.prefix}'.")
            return {'CANCELLED'}
        presets[current_preset][self.prefix][self.original_name] = self.new_name
        save_presets(presets)
        initialize_presets(context)
        self.report({'INFO'}, f"Rule '{self.original_name}' -> '{self.new_name}' added to prefix '{self.prefix}'.")
        return {'FINISHED'}

class OBJECT_OT_add_prefix(bpy.types.Operator):
    """Add a new renaming ruleset to give renaming rules"""
    bl_idname = "object.add_prefix"
    bl_label = "(Optional) Set Ruleset's Associated Prefix for Targeted Meshes/Armatures"

    new_prefix = bpy.props.StringProperty(
        name="Enter prefix to target specific meshes/armatures.",
        description="Leave blank to apply rules to all that don't have a matching prefix with another ruleset"
    )

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_prefix")

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        trimmed_prefix = self.new_prefix.strip()

        if trimmed_prefix in presets[current_preset]:
            self.report({'ERROR'}, f"Prefix '{trimmed_prefix}' already exists.")
            return {'CANCELLED'}
        
        presets[current_preset][trimmed_prefix] = {}
        save_presets(presets)
        initialize_presets(context)
        self.report({'INFO'}, f"Prefix '{trimmed_prefix}' added.")
        return {'FINISHED'}


# Operator to create a new preset
class OBJECT_OT_create_preset(bpy.types.Operator):
    """Create a new preset"""
    bl_idname = "object.create_preset"
    bl_label = "Create New Preset"

    new_preset_name = bpy.props.StringProperty(name="Preset Name", default="")

    def execute(self, context):
        if self.new_preset_name and self.new_preset_name not in presets:
            presets[self.new_preset_name] = {}
            save_presets(presets)
            context.scene.vgr_props.preset_dropdown = self.new_preset_name
            set_current_preset(context, self.new_preset_name)
            update_preset_dropdown(context)
            print(f"Created new preset: {self.new_preset_name}")
        else:
            self.report({'WARNING'}, "Preset name already exists")
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

class OBJECT_OT_duplicate_preset(bpy.types.Operator):
    """Duplicate the currently selected preset."""
    bl_idname = "object.duplicate_preset"
    bl_label = "Duplicate Preset"
    bl_options = {'REGISTER', 'UNDO'}

    new_preset_name = bpy.props.StringProperty(
        name="New Preset Name",
        description="Enter a name for the duplicated preset",
        default=""
    )

    def invoke(self, context, event):
        wm = context.window_manager
        # Pre-fill the new_preset_name with a default value
        self.new_preset_name = f"{context.scene.vgr_props.current_preset}_Copy"
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_preset_name")

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        new_preset_name = self.new_preset_name.strip()

        # Check if the new preset name is empty
        if not new_preset_name:
            self.report({'ERROR'}, "Preset name cannot be empty.")
            return {'CANCELLED'}

        # Check if the new preset name already exists
        if new_preset_name in presets:
            self.report({'ERROR'}, f"Preset '{new_preset_name}' already exists.")
            return {'CANCELLED'}

        # Duplicate the current preset
        presets[new_preset_name] = copy.deepcopy(presets[current_preset])
        save_presets(presets)
        initialize_presets(context)

        # Set the duplicated preset as the current and selected preset
        context.scene.vgr_props.preset_dropdown = new_preset_name
        set_current_preset(context, new_preset_name)
        update_preset_dropdown(context)

        self.report({'INFO'}, f"Preset '{current_preset}' duplicated as '{new_preset_name}' and selected.")
        return {'FINISHED'}

class OBJECT_OT_rename_preset(bpy.types.Operator):
    """Rename the currently selected preset."""
    bl_idname = "object.rename_preset"
    bl_label = "Rename Preset"
    bl_options = {'REGISTER', 'UNDO'}

    new_preset_name = bpy.props.StringProperty(
        name="New Preset Name",
        description="Enter a new name for the preset",
        default=""
    )

    def invoke(self, context, event):
        wm = context.window_manager
        # Pre-fill the new_preset_name with the current preset name
        self.new_preset_name = context.scene.vgr_props.current_preset
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_preset_name")

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        new_preset_name = self.new_preset_name.strip()

        # Check if the new preset name is empty
        if not new_preset_name:
            self.report({'ERROR'}, "Preset name cannot be empty.")
            return {'CANCELLED'}

        # Check if the new preset name already exists
        if new_preset_name in presets:
            self.report({'ERROR'}, f"Preset '{new_preset_name}' already exists.")
            return {'CANCELLED'}

        # Rename the preset
        presets[new_preset_name] = presets.pop(current_preset)
        save_presets(presets)
        initialize_presets(context)

        # Set the renamed preset as the current and selected preset
        context.scene.vgr_props.preset_dropdown = new_preset_name
        set_current_preset(context, new_preset_name)
        update_preset_dropdown(context)

        self.report({'INFO'}, f"Preset '{current_preset}' renamed to '{new_preset_name}' and selected.")
        return {'FINISHED'}

# Operator to remove the current preset with confirmation
class OBJECT_OT_remove_preset(bpy.types.Operator):
    """Delete the currently selected preset"""
    bl_idname = "object.remove_preset"
    bl_label = "Delete Preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        current_preset = context.scene.vgr_props.current_preset
        if current_preset in presets:
            if current_preset == "Default":
                self.report({'WARNING'}, "Cannot delete the Default preset.")
                return {'CANCELLED'}
            if len(presets) == 1:
                self.report({'WARNING'}, "Cannot remove the last preset.")
                return {'CANCELLED'}
            del presets[current_preset]
            save_presets(presets)
            new_preset = list(presets.keys())[0]
            context.scene.vgr_props.preset_dropdown = new_preset
            set_current_preset(context, new_preset)
            update_preset_dropdown(context)
            print(f"Removed preset: {current_preset}")
        else:
            self.report({'WARNING'}, "No preset selected or preset does not exist")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

class OBJECT_OT_import_preset(bpy.types.Operator):
    """Import presets from a JSON file"""
    bl_idname = "object.import_preset"
    bl_label = "Import Preset"

    filepath = bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        global presets
        try:
            with open(self.filepath, 'r') as f:
                imported_presets = json.load(f)
            
            # Track existing presets before import
            existing_presets = set(presets.keys())
            
            # Update presets with imported presets
            presets.update(imported_presets)
            save_presets(presets)
            initialize_presets(context)
            
            # Identify new presets added
            new_presets = list(imported_presets.keys())  # List of newly imported preset names
            
            if new_presets:
                # Select the last imported preset
                last_preset = new_presets[-1]
                context.scene.vgr_props.preset_dropdown = last_preset
                set_current_preset(context, last_preset)
                update_preset_dropdown(context)
                self.report({'INFO'}, f"Presets imported from '{self.filepath}' and '{last_preset}' selected.")
            else:
                self.report({'INFO'}, f"No new presets were imported from '{self.filepath}'.")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import presets: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class OBJECT_OT_export_preset(bpy.types.Operator):
    """Export presets to a JSON file"""
    bl_idname = "object.export_preset"
    bl_label = "Export Preset"

    filename_ext = ".json"

    filepath = bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob = bpy.props.StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        global presets
        try:
            if not self.filepath.lower().endswith(".json"):
                self.filepath += ".json"
            with open(self.filepath, 'w') as f:
                json.dump(presets, f, indent=4)
            self.report({'INFO'}, f"Presets exported to '{self.filepath}'.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export presets: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

# ============================
# Merge and Rename Operators
# ============================

class OBJECT_OT_rename_vertex_groups(bpy.types.Operator):
    """Rename selected meshes' vertex groups based on current preset rules. Groups targeting the same name will be merged"""
    bl_idname = "object.rename_vertex_groups"
    bl_label = "Apply Vertex Group Renaming"

    def execute(self, context):
        selected_meshes = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']

        if not selected_meshes:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

        current_preset = context.scene.vgr_props.current_preset
        current_rules = presets.get(current_preset, {})

        # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            mesh_to_armature = get_armatures_from_meshes(selected_meshes)
            # Check for multiple armatures in any mesh
            meshes_with_multiple_armatures = [mesh for mesh, armatures in mesh_to_armature.items() if isinstance(armatures, list)]
            if meshes_with_multiple_armatures:
                mesh_names = ", ".join([mesh.name for mesh in meshes_with_multiple_armatures])
                self.report({'ERROR'}, f"Meshes with multiple armatures detected: {mesh_names}. Cannot synchronize.")
                return {'CANCELLED'}

            # Get mapping of meshes to their single armature
            mesh_to_single_armature = {mesh: armature for mesh, armature in mesh_to_armature.items() if not isinstance(armature, list)}

            # Get all unique armatures
            armatures = list(set(mesh_to_single_armature.values()))

            # Get meshes linked to each armature
            armature_to_meshes = get_meshes_from_armatures(armatures)

        for mesh in selected_meshes:
            obj_name_lower = mesh.name.lower()
            matched_prefix = None
            # First, check if the mesh's name starts with any of the specified prefixes (excluding empty prefix)
            for prefix in current_rules.keys():
                if prefix != "" and obj_name_lower.startswith(prefix.lower()):
                    matched_prefix = prefix
                    break  # Use the first matching prefix
            # If no matching prefix is found, check if there is an empty prefix
            if matched_prefix is None and "" in current_rules:
                matched_prefix = ""
            # Apply renaming rules if a matching prefix is found
            if matched_prefix is not None:
                rules = current_rules[matched_prefix]
                # Mapping from new group names to list of source group names
                new_to_sources = {}
                for vg in mesh.vertex_groups:
                    if vg.name in rules:
                        new_name = rules[vg.name]
                        if new_name in new_to_sources:
                            new_to_sources[new_name].append(vg.name)
                        else:
                            new_to_sources[new_name] = [vg.name]

                # Handle merging
                for new_name, source_names in new_to_sources.items():
                    if len(source_names) > 1:
                        # Merge the groups
                        print(f"Merging groups {source_names} into '{new_name}' for mesh '{mesh.name}'")
                        merge_vertex_groups(mesh, new_name, source_names)
                    else:
                        # Single rename
                        old_name = source_names[0]
                        group = mesh.vertex_groups.get(old_name)
                        if group and group.name != new_name:
                            print(f"Renaming group '{old_name}' to '{new_name}' for mesh '{mesh.name}'")
                            group.name = new_name

        # Handle synchronization: Rename bones linked to these meshes
        if context.scene.vgr_props.sync_group_bone:
            for armature in armatures:
                # Rename bones in the armature linked to this mesh
                meshes_linked = armature_to_meshes.get(armature, [])
                for mesh in meshes_linked:
                    obj_name_lower = mesh.name.lower()
                    matched_prefix = None
                    for prefix in current_rules.keys():
                        if prefix != "" and obj_name_lower.startswith(prefix.lower()):
                            matched_prefix = prefix
                            break
                    if matched_prefix is None and "" in current_rules:
                        matched_prefix = ""
                    if matched_prefix is not None:
                        rules = current_rules[matched_prefix]
                        # Mapping from new bone names to list of source bone names
                        new_to_sources_bones = {}
                        for bone in armature.data.bones:
                            if bone.name in rules:
                                new_bone_name = rules[bone.name]
                                if new_bone_name in new_to_sources_bones:
                                    new_to_sources_bones[new_bone_name].append(bone.name)
                                else:
                                    new_to_sources_bones[new_bone_name] = [bone.name]

                        # Handle merging bones
                        for new_bone_name, source_bone_names in new_to_sources_bones.items():
                            if len(source_bone_names) > 1:
                                # Merge the bones
                                print(f"Merging bones {source_bone_names} into '{new_bone_name}' for armature '{armature.name}'")
                                merge_bones(armature, new_bone_name, source_bone_names)
                            else:
                                # Single rename
                                old_bone_name = source_bone_names[0]
                                bone = armature.data.bones.get(old_bone_name)
                                if bone and bone.name != new_bone_name:
                                    print(f"Renaming bone '{old_bone_name}' to '{new_bone_name}' for armature '{armature.name}'")
                                    bone.name = new_bone_name

        return {'FINISHED'}

class OBJECT_OT_undo_vertex_group_rename(bpy.types.Operator):
    """Rename selected meshes' vertex groups, reverse of the current preset rules"""
    bl_idname = "object.undo_vertex_group_rename"
    bl_label = "Reverse Vertex Group Renaming"

    def execute(self, context):
        selected_meshes = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']

        if not selected_meshes:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

        current_preset = context.scene.vgr_props.current_preset
        current_rules = presets.get(current_preset, {})

        # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            mesh_to_armature = get_armatures_from_meshes(selected_meshes)
            # Check for multiple armatures in any mesh
            meshes_with_multiple_armatures = [mesh for mesh, armatures in mesh_to_armature.items() if isinstance(armatures, list)]
            if meshes_with_multiple_armatures:
                mesh_names = ", ".join([mesh.name for mesh in meshes_with_multiple_armatures])
                self.report({'ERROR'}, f"Meshes with multiple armatures detected: {mesh_names}. Cannot synchronize.")
                return {'CANCELLED'}

            # Get mapping of meshes to their single armature
            mesh_to_single_armature = {mesh: armature for mesh, armature in mesh_to_armature.items() if not isinstance(armature, list)}

            # Get all unique armatures
            armatures = list(set(mesh_to_single_armature.values()))

            # Get meshes linked to each armature
            armature_to_meshes = get_meshes_from_armatures(armatures)

        for mesh in selected_meshes:
            obj_name_lower = mesh.name.lower()
            matched_prefix = None
            # First, check if the mesh's name starts with any of the specified prefixes (excluding empty prefix)
            for prefix in current_rules.keys():
                if prefix != "" and obj_name_lower.startswith(prefix.lower()):
                    matched_prefix = prefix
                    break  # Use the first matching prefix
            # If no matching prefix is found, check if there is an empty prefix
            if matched_prefix is None and "" in current_rules:
                matched_prefix = ""
            # Apply undo renaming rules if a matching prefix is found
            if matched_prefix is not None:
                rules = current_rules[matched_prefix]
                reverse_rules = {new_name: original_name for original_name, new_name in rules.items()}
                for vg in mesh.vertex_groups:
                    if vg.name in reverse_rules:
                        original_name = reverse_rules[vg.name]
                        print(f"Restoring group '{vg.name}' to '{original_name}' for mesh '{mesh.name}'")
                        vg.name = original_name

        # Handle synchronization: Undo bone renames linked to these meshes
        if context.scene.vgr_props.sync_group_bone:
            for armature in armatures:
                # Undo renames in the armature linked to this mesh
                meshes_linked = armature_to_meshes.get(armature, [])
                for mesh in meshes_linked:
                    obj_name_lower = mesh.name.lower()
                    matched_prefix = None
                    for prefix in current_rules.keys():
                        if prefix != "" and obj_name_lower.startswith(prefix.lower()):
                            matched_prefix = prefix
                            break
                    if matched_prefix is None and "" in current_rules:
                        matched_prefix = ""
                    if matched_prefix is not None:
                        rules = current_rules[matched_prefix]
                        reverse_rules = {new_name: original_name for original_name, new_name in rules.items()}
                        for bone in armature.data.bones:
                            if bone.name in reverse_rules:
                                original_name = reverse_rules[bone.name]
                                print(f"Restoring bone '{bone.name}' to '{original_name}' for armature '{armature.name}'")
                                bone.name = original_name

        return {'FINISHED'}

class OBJECT_OT_rename_bones(bpy.types.Operator):
    """Rename selected armatures' bones based on current preset rules. This will affect linked meshes' vertex group names as well"""
    bl_idname = "object.rename_bones"
    bl_label = "Apply Bone Renaming"

    def execute(self, context):
        selected_armatures = [obj for obj in bpy.context.selected_objects if obj.type == 'ARMATURE']

        if not selected_armatures:
            self.report({'WARNING'}, "No armatures selected.")
            return {'CANCELLED'}

        current_preset = context.scene.vgr_props.current_preset
        current_rules = presets.get(current_preset, {})

         # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            armature_to_meshes = get_meshes_from_armatures(selected_armatures)
            # Check for armatures linked to multiple meshes
            armatures_with_multiple_meshes = [armature for armature, meshes in armature_to_meshes.items() if len(meshes) > 1]
            if armatures_with_multiple_meshes:
                armature_names = ", ".join([arm.name for arm in armatures_with_multiple_meshes])
            #    self.report({'ERROR'}, f"Armatures linked to multiple meshes detected: {armature_names}. Cannot synchronize.")
            #    return {'CANCELLED'}
        
            # Get mapping of armatures to their single mesh
            armature_to_single_mesh = {armature: meshes[0] for armature, meshes in armature_to_meshes.items()}
        
            # Get all unique meshes
            meshes = list(set(armature_to_single_mesh.values()))
        
            # Get armatures linked to each mesh
            mesh_to_armatures = get_armatures_from_meshes(meshes)

        for armature in selected_armatures:
            armature_name_lower = armature.name.lower()
            matched_prefix = None
            # First, check if the armature's name starts with any of the specified prefixes (excluding empty prefix)
            for prefix in current_rules.keys():
                if prefix != "" and armature_name_lower.startswith(prefix.lower()):
                    matched_prefix = prefix
                    break  # Use the first matching prefix
            # If no matching prefix is found, check if there is an empty prefix
            if matched_prefix is None and "" in current_rules:
                matched_prefix = ""
            # Apply renaming rules if a matching prefix is found
            if matched_prefix is not None:
                rules = current_rules[matched_prefix]
                # Mapping from new bone names to list of source bone names
                new_to_sources_bones = {}
                for bone in armature.data.bones:
                    if bone.name in rules:
                        new_bone_name = rules[bone.name]
                        if new_bone_name in new_to_sources_bones:
                            new_to_sources_bones[new_bone_name].append(bone.name)
                        else:
                            new_to_sources_bones[new_bone_name] = [bone.name]

                # Handle merging bones
                for new_bone_name, source_bone_names in new_to_sources_bones.items():
                    if len(source_bone_names) > 1:
                        # Merge the bones
                        print(f"Merging bones {source_bone_names} into '{new_bone_name}' for armature '{armature.name}'")
                        merge_bones(armature, new_bone_name, source_bone_names)
                    else:
                        # Single rename
                        old_bone_name = source_bone_names[0]
                        bone = armature.data.bones.get(old_bone_name)
                        if bone and bone.name != new_bone_name:
                            print(f"Renaming bone '{old_bone_name}' to '{new_bone_name}' for armature '{armature.name}'")
                            bone.name = new_bone_name

        # Handle synchronization: Rename vertex groups linked to these armatures
        #if context.scene.vgr_props.sync_group_bone:
        #    for mesh in meshes:
        #        mirror_names(mesh, is_bone=False)

        return {'FINISHED'}

class OBJECT_OT_undo_bone_renames(bpy.types.Operator):
    """Rename selected armatures' bones, reverse of the current preset rules. This will affect linked meshes' vertex group names as well"""
    bl_idname = "object.undo_bone_renames"
    bl_label = "Reverse Bone Renaming"

    def execute(self, context):
        selected_armatures = [obj for obj in bpy.context.selected_objects if obj.type == 'ARMATURE']

        if not selected_armatures:
            self.report({'WARNING'}, "No armatures selected.")
            return {'CANCELLED'}

        current_preset = context.scene.vgr_props.current_preset
        current_rules = presets.get(current_preset, {})

         # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            armature_to_meshes = get_meshes_from_armatures(selected_armatures)
            # Check for armatures linked to multiple meshes
            armatures_with_multiple_meshes = [armature for armature, meshes in armature_to_meshes.items() if len(meshes) > 1]
            if armatures_with_multiple_meshes:
                armature_names = ", ".join([arm.name for arm in armatures_with_multiple_meshes])
            #    self.report({'ERROR'}, f"Armatures linked to multiple meshes detected: {armature_names}. Cannot synchronize.")
            #    return {'CANCELLED'}
        
            # Get mapping of armatures to their single mesh
            armature_to_single_mesh = {armature: meshes[0] for armature, meshes in armature_to_meshes.items()}
        
            # Get all unique meshes
            meshes = list(set(armature_to_single_mesh.values()))
        
            # Get armatures linked to each mesh
            mesh_to_armatures = get_armatures_from_meshes(meshes)

        for armature in selected_armatures:
            armature_name_lower = armature.name.lower()
            matched_prefix = None
            # First, check if the armature's name starts with any of the specified prefixes (excluding empty prefix)
            for prefix in current_rules.keys():
                if prefix != "" and armature_name_lower.startswith(prefix.lower()):
                    matched_prefix = prefix
                    break  # Use the first matching prefix
            # If no matching prefix is found, check if there is an empty prefix
            if matched_prefix is None and "" in current_rules:
                matched_prefix = ""
            # Apply undo renaming rules if a matching prefix is found
            if matched_prefix is not None:
                rules = current_rules[matched_prefix]
                reverse_rules = {new_name: original_name for original_name, new_name in rules.items()}
                for bone in armature.data.bones:
                    if bone.name in reverse_rules:
                        original_name = reverse_rules[bone.name]
                        print(f"Restoring bone '{bone.name}' to '{original_name}' for armature '{armature.name}'")
                        bone.name = original_name

        # Handle synchronization: Undo vertex group renames linked to these armatures
        #if context.scene.vgr_props.sync_group_bone:
        #    for mesh in meshes:
        #        current_rules = presets.get(context.scene.vgr_props.current_preset, {})
        #        obj_name_lower = mesh.name.lower()
        #        matched_prefix = None
        #        for prefix in current_rules.keys():
        #            if prefix != "" and obj_name_lower.startswith(prefix.lower()):
        #                matched_prefix = prefix
        #                break
        #        if matched_prefix is None and "" in current_rules:
        #            matched_prefix = ""
        #        if matched_prefix is not None:
        #            rules = current_rules[matched_prefix]
        #            reverse_rules = {new_name: original_name for original_name, new_name in rules.items()}
        #            for vg in mesh.vertex_groups:
        #                if vg.name in reverse_rules:
        #                    original_name = reverse_rules[vg.name]
        #                    print(f"Restoring group '{vg.name}' to '{original_name}' for mesh '{mesh.name}'")
        #                    vg.name = original_name

        return {'FINISHED'}

class OBJECT_OT_quick_mirror_vertex_groups(bpy.types.Operator):
    """Quickly swap selected meshes' vertex group names beginning with `L_` and `R_`"""
    bl_idname = "object.quick_mirror_vertex_groups"
    bl_label = "Quick Mirror L and R Vertex Groups"

    def execute(self, context):
        selected_meshes = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']

        if not selected_meshes:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

         # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            mesh_to_armature = get_armatures_from_meshes(selected_meshes)
            # Check for multiple armatures in any mesh
            meshes_with_multiple_armatures = [mesh for mesh, armatures in mesh_to_armature.items() if isinstance(armatures, list)]
            if meshes_with_multiple_armatures:
                mesh_names = ", ".join([mesh.name for mesh in meshes_with_multiple_armatures])
                self.report({'ERROR'}, f"Meshes with multiple armatures detected: {mesh_names}. Cannot synchronize.")
                return {'CANCELLED'}

            # Get mapping of meshes to their single armature
            mesh_to_single_armature = {mesh: armature for mesh, armature in mesh_to_armature.items() if not isinstance(armature, list)}

            # Get all unique armatures
            armatures = list(set(mesh_to_single_armature.values()))

            # Get meshes linked to each armature
            armature_to_meshes = get_meshes_from_armatures(armatures)

        # Mirror vertex groups for each selected mesh
        for mesh in selected_meshes:
            mirror_names(mesh, is_bone=False)

        # Handle synchronization: Mirror bones linked to these armatures
        if context.scene.vgr_props.sync_group_bone:
            for armature in armatures:
                mirror_names(armature, is_bone=True)
            # This was missing before
            for mesh in selected_meshes:
                mirror_names(mesh, is_bone=False)

        return {'FINISHED'}

class OBJECT_OT_quick_mirror_bone_names(bpy.types.Operator):
    """Quickly swap selected armatures' bone names beginning with `L_` and `R_`. This will affect linked meshes' vertex group names as well"""
    bl_idname = "object.quick_mirror_bone_names"
    bl_label = "Quick Mirror L and R Bone Names"

    def execute(self, context):
        selected_armatures = [obj for obj in bpy.context.selected_objects if obj.type == 'ARMATURE']

        if not selected_armatures:
            self.report({'WARNING'}, "No armatures selected.")
            return {'CANCELLED'}

        # Handle synchronization if enabled
        if context.scene.vgr_props.sync_group_bone:
            armature_to_meshes = get_meshes_from_armatures(selected_armatures)
            # Check for armatures linked to multiple meshes
            armatures_with_multiple_meshes = [armature for armature, meshes in armature_to_meshes.items() if len(meshes) > 1]
            if armatures_with_multiple_meshes:
                armature_names = ", ".join([arm.name for arm in armatures_with_multiple_meshes])
            #    self.report({'ERROR'}, f"Armatures linked to multiple meshes detected: {armature_names}. Cannot synchronize.")
            #    return {'CANCELLED'}
        
            # Get mapping of armatures to their single mesh
            armature_to_single_mesh = {armature: meshes[0] for armature, meshes in armature_to_meshes.items()}
        
            # Get all unique meshes
            meshes = list(set(armature_to_single_mesh.values()))
        
            # Get armatures linked to each mesh
            mesh_to_armatures = get_armatures_from_meshes(meshes)

        # Mirror bone names for each selected armature
        for armature in selected_armatures:
            mirror_names(armature, is_bone=True)

        # Handle synchronization: Mirror vertex groups linked to these armatures
        #if context.scene.vgr_props.sync_group_bone:
        #    for armature in armatures:
        #        linked_meshes = armature_to_meshes.get(armature, [])
        #        for mesh in linked_meshes:
        #            mirror_names(mesh, is_bone=False)

        return {'FINISHED'}

# ============================
# Custom Menu for Preset Selection
# ============================

class VGR_MT_preset_menu(bpy.types.Menu):
    bl_label = "Select Preset"
    bl_idname = "VGR_MT_preset_menu"

    def draw(self, context):
        layout = self.layout
        for preset_name in sorted(presets.keys()):
            op = layout.operator("vgr.select_preset", text=preset_name)
            op.preset_name = preset_name

# Operator to handle preset selection
class VGR_OT_select_preset(bpy.types.Operator):
    bl_idname = "vgr.select_preset"
    bl_label = "Select Preset"

    preset_name = bpy.props.StringProperty()

    def execute(self, context):
        context.scene.vgr_props.preset_dropdown = self.preset_name
        set_current_preset(context, self.preset_name)
        return {'FINISHED'}

# ============================
# Panel Definition
# ============================

class VIEW3D_PT_vertex_group_renamer(bpy.types.Panel):
    bl_label = "Vertex Group Renamer"
    bl_idname = "VIEW3D_PT_vertex_group_renamer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Vertex Group Renamer'  # This creates a new sidebar tab

    def draw(self, context):
        layout = self.layout

        # Ensure presets are initialized
        if not presets:
            initialize_presets(context)

        # Ensure the property exists
        if not hasattr(context.scene, "vgr_props") or not hasattr(context.scene.vgr_props, "preset_dropdown"):
            layout.label(text="Loading presets...")
            return

        props = context.scene.vgr_props

        # Dropdown menu for presets
        layout.label(text="Select Preset:")
        layout.menu("VGR_MT_preset_menu", text=props.preset_dropdown)
        is_default = (props.preset_dropdown == "Default")

        # Add label "Manage Presets:"
        layout.label(text="Manage Presets:")

        # Group "New Preset" and "Duplicate Preset" horizontally
        row = layout.row(align=True)
        row.operator("object.create_preset", text="Create New Preset")
        row.operator("object.duplicate_preset", text="Duplicate Preset")

        # Group "Rename Preset" and "Delete Preset" horizontally beneath
        row = layout.row(align=True)
        row.enabled = not is_default  # Disable the row if "Default" preset is selected
        row.operator("object.rename_preset", text="Rename Preset")
        row.operator("object.remove_preset", text="Delete Preset")

        # Add label "Import/Export Presets:"
        layout.label(text="Import/Export Presets:")

        # "Import Preset" button
        layout.operator("object.import_preset", text="Import Preset")
        # "Export Preset" button
        layout.operator("object.export_preset", text="Export Preset")

        # Display current renaming rules
        self.display_existing_rules(layout, context)

        # "Add New Prefix" button underneath all prefixes
        layout.operator("object.add_prefix", text="Add Renaming Ruleset")

        # Add label "Renaming Actions:"
        layout.label(text="Renaming Actions (Vertex Groups):")

        # Group "Rename Vertex Groups" and "Undo Group Renames" buttons side by side
        row = layout.row(align=True)
        row.operator("object.rename_vertex_groups", text="Apply Vertex Group Renaming")
        row.operator("object.undo_vertex_group_rename", text="Reverse Vertex Group Renaming")
        
        # "Quick Mirror L and R Groups" button
        layout.operator("object.quick_mirror_vertex_groups", text="Quick Mirror Left and Right Vertex Groups")
        
        # Add the synchronization checkbox
        layout.prop(props, "sync_group_bone", text="Sync Vertex Group and Bone Renaming")

        # Add label "Renaming Actions:"
        layout.label(text="Renaming Actions (Armature Bones):")

        # Group "Rename Bones" and "Undo Bone Renames" buttons side by side
        row = layout.row(align=True)
        row.operator("object.rename_bones", text="Apply Bone Renaming")
        row.operator("object.undo_bone_renames", text="Reverse Bone Renaming")
        # "Quick Mirror L and R Bone Names" button
        layout.operator("object.quick_mirror_bone_names", text="Quick Mirror Left and Right Bone Names")

    def display_existing_rules(self, layout, context):
        global prefix_expand_states
        current_preset = context.scene.vgr_props.current_preset
        current_rules = presets.get(current_preset, {})
        layout.label(text=f"Current Preset: {current_preset}")

        if current_rules:
            # Use enumerate to get row numbers starting from 1
            for rowNumber, (prefix, rules) in enumerate(current_rules.items(), start=1):
                is_expanded = prefix_expand_states.get(prefix, False)

                # Collapsible section for each prefix
                box = layout.box()
                row = box.row()

                # Display the prefix name with row number only if prefix is not empty
                if prefix:
                    # If prefix is not empty, show "Ruleset [rowNumber] (Prefix: [prefix])"
                    row.label(text=f"Ruleset {rowNumber} (Prefix: {prefix})")
                else:
                    # If prefix is empty, show the placeholder without "Ruleset [rowNumber]"
                    row.label(text=f"Ruleset {rowNumber} <No Prefix - Rules apply to all without matching prefix.>")

                # Add a "Rename" button
                rename_op = row.operator("object.rename_prefix", text="", icon='GREASEPENCIL')
                rename_op.prefix = prefix

                # Button to expand/collapse the prefix container
                expand_icon = "TRIA_DOWN" if is_expanded else "TRIA_RIGHT"
                toggle_op = row.operator("object.toggle_expand_prefix", text="", icon=expand_icon, emboss=False)
                toggle_op.prefix = prefix

                # Remove the prefix
                remove_op = row.operator("object.remove_prefix", text="", icon='X', emboss=False)
                remove_op.prefix = prefix

                if is_expanded:
                    # Display each renaming rule under the prefix
                    for original, new in rules.items():
                        rule_box = box.box()
                        rule_row = rule_box.row()
                        # Property names
                        original_prop = f"rule_edit_original_{sanitize_property_name(current_preset)}_{sanitize_property_name(prefix)}_{sanitize_property_name(original)}"
                        new_prop = f"rule_edit_new_{sanitize_property_name(current_preset)}_{sanitize_property_name(prefix)}_{sanitize_property_name(original)}"
                        # Editable fields for renaming rules
                        rule_row.prop(bpy.context.scene, original_prop, text="Original Name")
                        rule_row.prop(bpy.context.scene, new_prop, text="New Name")

                        # Remove button for the rule
                        remove_rule_op = rule_row.operator("object.remove_rule", text="", icon='X', emboss=False)
                        remove_rule_op.prefix = prefix
                        remove_rule_op.original_name = original
                    # Button to add a new rule
                    add_rule_op = box.operator("object.add_rule", text="Add New Rule")
                    add_rule_op.prefix = prefix
        else:
            layout.label(text="No renaming rules for this preset.")

# ============================
# Registration Functions
# ============================

def register():
    # Register the PropertyGroup
    bpy.utils.register_class(VertexGroupRenamerProperties)
    bpy.types.Scene.vgr_props = bpy.props.PointerProperty(type=VertexGroupRenamerProperties)

    # Register new classes
    bpy.utils.register_class(VGR_MT_preset_menu)
    bpy.utils.register_class(VGR_OT_select_preset)

    # Register all operator and panel classes
    bpy.utils.register_class(OBJECT_OT_toggle_expand_prefix)
    bpy.utils.register_class(OBJECT_OT_remove_prefix)
    bpy.utils.register_class(OBJECT_OT_rename_prefix)
    bpy.utils.register_class(OBJECT_OT_remove_rule)
    bpy.utils.register_class(OBJECT_OT_add_rule)
    bpy.utils.register_class(OBJECT_OT_add_prefix)
    bpy.utils.register_class(OBJECT_OT_create_preset)
    bpy.utils.register_class(OBJECT_OT_import_preset)
    bpy.utils.register_class(OBJECT_OT_export_preset)
    bpy.utils.register_class(OBJECT_OT_remove_preset)
    bpy.utils.register_class(OBJECT_OT_rename_preset)
    bpy.utils.register_class(OBJECT_OT_duplicate_preset)
    bpy.utils.register_class(OBJECT_OT_quick_mirror_vertex_groups)
    bpy.utils.register_class(OBJECT_OT_rename_vertex_groups)
    bpy.utils.register_class(OBJECT_OT_undo_vertex_group_rename)
    bpy.utils.register_class(OBJECT_OT_rename_bones)
    bpy.utils.register_class(OBJECT_OT_undo_bone_renames)
    bpy.utils.register_class(OBJECT_OT_quick_mirror_bone_names)
    bpy.utils.register_class(VIEW3D_PT_vertex_group_renamer)

    # Initialize presets will be called when the panel is drawn
    print("Vertex Group Renamer Addon Registered")

def unregister():
    unregister_dynamic_properties()
    # Remove the PropertyGroup
    del bpy.types.Scene.vgr_props
    bpy.utils.unregister_class(VertexGroupRenamerProperties)

    # Unregister new classes
    bpy.utils.unregister_class(VGR_MT_preset_menu)
    bpy.utils.unregister_class(VGR_OT_select_preset)

    # Unregister all operator and panel classes
    bpy.utils.unregister_class(OBJECT_OT_toggle_expand_prefix)
    bpy.utils.unregister_class(OBJECT_OT_remove_prefix)
    bpy.utils.unregister_class(OBJECT_OT_rename_prefix)
    bpy.utils.unregister_class(OBJECT_OT_remove_rule)
    bpy.utils.unregister_class(OBJECT_OT_add_rule)
    bpy.utils.unregister_class(OBJECT_OT_add_prefix)
    bpy.utils.unregister_class(OBJECT_OT_create_preset)
    bpy.utils.unregister_class(OBJECT_OT_import_preset)
    bpy.utils.unregister_class(OBJECT_OT_export_preset)
    bpy.utils.unregister_class(OBJECT_OT_remove_preset)
    bpy.utils.unregister_class(OBJECT_OT_rename_preset)
    bpy.utils.unregister_class(OBJECT_OT_duplicate_preset)
    bpy.utils.unregister_class(OBJECT_OT_quick_mirror_vertex_groups)
    bpy.utils.unregister_class(OBJECT_OT_rename_vertex_groups)
    bpy.utils.unregister_class(OBJECT_OT_undo_vertex_group_rename)
    bpy.utils.unregister_class(OBJECT_OT_rename_bones)
    bpy.utils.unregister_class(OBJECT_OT_undo_bone_renames)
    bpy.utils.unregister_class(OBJECT_OT_quick_mirror_bone_names)
    bpy.utils.unregister_class(VIEW3D_PT_vertex_group_renamer)

    print("Vertex Group Renamer Addon Unregistered")

if __name__ == "__main__":
    register()
