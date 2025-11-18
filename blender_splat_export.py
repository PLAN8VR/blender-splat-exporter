bl_info = {
    "name": "Gaussian Splat Exporter",
    "author": "PLAN8",
    "version": (0, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Gaussian Splat | File > Export > Gaussian Splat (.ply)",
    "description": "Export mesh geometry to Gaussian Splat format using Playcanvas' splat-transform",
    "category": "Import-Export",
}

import bpy
import bmesh
import json
import os
import subprocess
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty, EnumProperty, PointerProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector, Matrix
import math


class GaussianSplatSettings(bpy.types.PropertyGroup):
    """Settings for Gaussian Splat export"""
    
    splat_transform_path: StringProperty(
        name="splat-transform Command",
        description="Command to run splat-transform (e.g., 'splat-transform' if globally installed, or full path)",
        default="splat-transform",
    )

    overwrite_output: BoolProperty(
        name="Overwrite Existing File",
        description="Overwrite output file if it exists",
        default=True
    )

    keep_mjs_file: BoolProperty(
        name="Export .mjs File",
        description="Save the .mjs generator file in the export directory",
        default=False
    )

    use_frame_number: BoolProperty(
        name="Use Frame Number in Filename",
        description="Append the current frame number to the exported filename",
        default=False
    )

    batch_export_animation: BoolProperty(
        name="Batch Export Animation",
        description="Export all frames from timeline start to end",
        default=False
    )

    sample_density: FloatProperty(
        name="Sample Density",
        description="Number of splats per square unit (only used in Surface Sampling mode)",
        default=100.0,
        min=1.0,
        max=10000.0
    )

    sampling_mode: EnumProperty(
        name="Sampling Mode",
        description="How to generate splats from the mesh",
        items=(
            ('VERTICES', "Use Vertices", "Create one splat per vertex"),
            ('SURFACE', "Surface Sampling", "Sample splats across surface area"),
        ),
        default='VERTICES',
    )

    splat_scale: FloatProperty(
        name="Global Scale Multiplier",
        description="Global scale multiplier applied to all splats (multiplied with auto-calculated size based on vertex proximity)",
        default=1.0,
        min=0.001,
        max=100.0
    )
    
    use_auto_scale: BoolProperty(
        name="Auto Scale from Vertex Proximity",
        description="Automatically scale splats based on distance to nearest vertex",
        default=True
    )

    splat_opacity: FloatProperty(
        name="Global Opacity Multiplier",
        description="Global opacity multiplier applied to all splats (multiplied with color attribute alpha)",
        default=1.0,
        min=0.0,
        max=1.0
    )

    use_vertex_colors: BoolProperty(
        name="Use Vertex Colors",
        description="Use vertex colors if available",
        default=True
    )

    use_normals: BoolProperty(
        name="Orient to Normals",
        description="Orient splats perpendicular to surface normals",
        default=True
    )

    bake_mode: EnumProperty(
        name="Bake Mode",
        description="What to bake from the material",
        items=(
            ('DIFFUSE', "Diffuse", "Bake diffuse color only (Base Color without lighting)"),
            ('EMIT', "Emission", "Bake emission only"),
            ('COMBINED', "Combined", "Bake full render with lighting (slower, requires proper scene lighting)"),
            ('VERTEX_ONLY', "Vertex Colors Only", "Don't bake textures, use existing vertex colors"),
        ),
        default='DIFFUSE',
    )
    
    bake_samples: IntProperty(
        name="Bake Samples",
        description="Number of samples for Combined bake mode (higher = better quality but slower)",
        default=16,
        min=1,
        max=1024
    )

    axis_forward: EnumProperty(
        name="Forward",
        items=(
            ('X', "X Forward", ""),
            ('Y', "Y Forward", ""),
            ('Z', "Z Forward", ""),
            ('-X', "-X Forward", ""),
            ('-Y', "-Y Forward", ""),
            ('-Z', "-Z Forward", ""),
        ),
        default='Z',
    )

    axis_up: EnumProperty(
        name="Up",
        items=(
            ('X', "X Up", ""),
            ('Y', "Y Up", ""),
            ('Z', "Z Up", ""),
            ('-X', "-X Up", ""),
            ('-Y', "-Y Up", ""),
            ('-Z', "-Z Up", ""),
        ),
        default='-Y',
    )

    export_path: StringProperty(
        name="Export Path",
        description="Path for the exported .ply file",
        default="",
        subtype='FILE_PATH'
    )


class GAUSSIANSPLAT_PT_MainPanel(bpy.types.Panel):
    """Main panel for Gaussian Splat export in 3D view sidebar"""
    bl_label = "Gaussian Splat Export"
    bl_idname = "GAUSSIANSPLAT_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Gaussian Splat'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.gaussian_splat_settings
        
        # Export path
        box = layout.box()
        box.label(text="Export Settings:", icon='EXPORT')
        box.prop(settings, "export_path")
        box.prop(settings, "splat_transform_path")
        box.prop(settings, "overwrite_output")
        box.prop(settings, "keep_mjs_file")
        
        # Animation export options
        box = layout.box()
        box.label(text="Animation Export:", icon='TIME')
        box.prop(settings, "use_frame_number")
        box.prop(settings, "batch_export_animation")
        if settings.batch_export_animation:
            row = box.row()
            row.label(text=f"Will export frames {context.scene.frame_start} to {context.scene.frame_end}")
        
        # Sampling options
        box = layout.box()
        box.label(text="Sampling Options:", icon='MESH_DATA')
        box.prop(settings, "sampling_mode")
        if settings.sampling_mode == 'SURFACE':
            box.prop(settings, "sample_density")
        
        # Splat properties
        box = layout.box()
        box.label(text="Splat Properties:", icon='PARTICLE_DATA')
        box.prop(settings, "use_auto_scale")
        box.prop(settings, "splat_scale")
        box.prop(settings, "splat_opacity")
        
        # Color options
        box = layout.box()
        box.label(text="Color Options:", icon='COLOR')
        box.prop(settings, "use_vertex_colors")
        box.prop(settings, "bake_mode")
        if settings.bake_mode == 'COMBINED':
            box.prop(settings, "bake_samples")
            box.label(text="Note: Requires proper scene lighting", icon='INFO')
        box.prop(settings, "use_normals")
        
        # Axis conversion
        box = layout.box()
        box.label(text="Axis Conversion:", icon='ORIENTATION_GIMBAL')
        box.prop(settings, "axis_forward")
        box.prop(settings, "axis_up")
        
        # Export button
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("export_scene.gaussian_splat_direct", text="Export Gaussian Splat", icon='EXPORT')


class GAUSSIANSPLAT_OT_DirectExport(bpy.types.Operator):
    """Export Gaussian Splat directly from the side panel"""
    bl_idname = "export_scene.gaussian_splat_direct"
    bl_label = "Export Gaussian Splat"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.gaussian_splat_settings
        
        # Validate export path
        if not settings.export_path:
            self.report({'ERROR'}, "Please specify an export path")
            return {'CANCELLED'}
        
        # Get selected objects
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Check if batch export is enabled
        if settings.batch_export_animation:
            return self.batch_export_frames(context, settings, selected_objects)
        else:
            return self.export_single_frame(context, settings, selected_objects, context.scene.frame_current)

    def export_single_frame(self, context, settings, selected_objects, frame_number):
        """Export a single frame"""
        # Set the frame
        context.scene.frame_set(frame_number)
        
        # Temporarily bake textures to vertex colors if needed
        temp_vcol_layers = {}
        for obj in selected_objects:
            if obj.active_material and obj.active_material.use_nodes:
                temp_vcol_layers[obj] = self.bake_temp_vertex_colors(obj, context, settings)
        
        # Build filepath with optional frame number
        base_path = settings.export_path
        if not base_path.lower().endswith('.ply'):
            base_path += '.ply'
        
        if settings.use_frame_number:
            # Insert frame number before extension
            base_name = os.path.splitext(base_path)[0]
            filepath = f"{base_name}_{frame_number:04d}.ply"
        else:
            filepath = base_path
        
        # Derive output directory and .mjs filename
        export_dir = os.path.dirname(filepath)
        if not export_dir:
            export_dir = bpy.path.abspath("//")
            filepath = os.path.join(export_dir, os.path.basename(filepath))
        
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        generator_path = os.path.join(export_dir, f"{base_name}.mjs")

        try:
            # Get axis conversion matrix
            axis_matrix = get_axis_conversion_matrix(settings)

            # Sample points from meshes
            all_samples = []
            for obj in selected_objects:
                if settings.sampling_mode == 'VERTICES':
                    samples = sample_vertices(obj, context, axis_matrix, settings)
                else:
                    samples = sample_mesh(obj, context, axis_matrix, settings)
                all_samples.extend(samples)

            self.report({'INFO'}, f"Frame {frame_number}: Sampled {len(all_samples)} points from {len(selected_objects)} object(s)")

            # Generate the mesh generator file
            create_mesh_generator(generator_path, all_samples)

            # Build splat-transform command as a list
            cmd = [settings.splat_transform_path]
            if settings.overwrite_output:
                cmd.append('-w')
            cmd.extend([generator_path, filepath])
            
            # Run splat-transform
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True
            )

            if result.returncode != 0:
                self.report({'ERROR'}, f"splat-transform failed: {result.stderr}")
                return {'CANCELLED'}

            # Delete .mjs file if not keeping it
            if not settings.keep_mjs_file and os.path.exists(generator_path):
                try:
                    os.remove(generator_path)
                except Exception as e:
                    self.report({'WARNING'}, f"Could not delete .mjs file: {str(e)}")

            self.report({'INFO'}, f"Successfully exported to {filepath}")
            result_status = {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            result_status = {'CANCELLED'}
        
        finally:
            # Clean up temporary vertex color layers
            for obj, vcol_layer in temp_vcol_layers.items():
                if vcol_layer and vcol_layer.name in obj.data.vertex_colors:
                    obj.data.vertex_colors.remove(vcol_layer)
        
        return result_status

    def batch_export_frames(self, context, settings, selected_objects):
        """Export all frames in the timeline range"""
        start_frame = context.scene.frame_start
        end_frame = context.scene.frame_end
        original_frame = context.scene.frame_current
        
        total_frames = end_frame - start_frame + 1
        self.report({'INFO'}, f"Starting batch export of {total_frames} frames...")
        
        success_count = 0
        fail_count = 0
        
        for frame in range(start_frame, end_frame + 1):
            result = self.export_single_frame(context, settings, selected_objects, frame)
            if result == {'FINISHED'}:
                success_count += 1
            else:
                fail_count += 1
        
        # Restore original frame
        context.scene.frame_set(original_frame)
        
        if fail_count == 0:
            self.report({'INFO'}, f"Batch export complete! Successfully exported {success_count} frames.")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"Batch export finished with errors. Success: {success_count}, Failed: {fail_count}")
            return {'FINISHED'}

    def bake_temp_vertex_colors(self, obj, context, settings):
        """Temporarily bake textures to vertex colors for current frame"""
        mesh = obj.data
        material = obj.active_material
        
        # Skip baking if mode is vertex colors only
        if settings.bake_mode == 'VERTEX_ONLY':
            return None
        
        # Check if material has any texture connections
        has_textures = False
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    if node.inputs['Base Color'].is_linked or (node.inputs.get('Emission Color') and node.inputs.get('Emission Color').is_linked):
                        has_textures = True
                        break
        
        if not has_textures and settings.bake_mode != 'COMBINED':
            return None
        
        # Create temporary vertex color layer
        temp_name = "_temp_bake_"
        if temp_name in mesh.vertex_colors:
            vcol_layer = mesh.vertex_colors[temp_name]
        else:
            vcol_layer = mesh.vertex_colors.new(name=temp_name)
        
        # Set as active so it gets picked up during export
        mesh.vertex_colors.active = vcol_layer
        
        # Use appropriate baking method based on mode
        if settings.bake_mode == 'COMBINED':
            # Use Blender's built-in bake system for full lighting
            self.bake_combined_mode(obj, vcol_layer, context, settings)
        else:
            # Use direct texture sampling for diffuse/emission
            self.bake_texture_mode(obj, vcol_layer, material, settings)
        
        return vcol_layer

    def bake_texture_mode(self, obj, vcol_layer, material, settings):
        """Bake textures directly by sampling (fast, no lighting)"""
        mesh = obj.data
        
        if not mesh.uv_layers.active:
            # No UVs, use material base color
            color = self.get_material_color_by_mode(material, settings.bake_mode)
            for poly in mesh.polygons:
                for loop_idx in poly.loop_indices:
                    vcol_layer.data[loop_idx].color = color
            return
        
        uv_layer = mesh.uv_layers.active
        
        # Sample texture for each loop
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                loop = mesh.loops[loop_idx]
                uv = uv_layer.data[loop_idx].uv
                
                color = self.sample_material_at_uv(material, uv, settings.bake_mode)
                vcol_layer.data[loop_idx].color = color

    def bake_combined_mode(self, obj, vcol_layer, context, settings):
        """Bake using Blender's render bake system (includes lighting)"""
        # Store original settings
        original_engine = context.scene.render.engine
        
        try:
            # Set up for baking
            context.scene.render.engine = 'CYCLES'
            context.scene.cycles.samples = settings.bake_samples
            
            # Ensure the object is selected
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            
            # Store original active color attribute
            mesh = obj.data
            original_active = mesh.color_attributes.active_color if hasattr(mesh, 'color_attributes') else None
            
            # Set our temp layer as active for baking
            if hasattr(mesh, 'color_attributes'):
                for attr in mesh.color_attributes:
                    if attr.name == vcol_layer.name:
                        mesh.color_attributes.active_color = attr
                        break
            
            # Perform the bake
            bpy.ops.object.bake(
                type='COMBINED',
                use_selected_to_active=False,
                target='VERTEX_COLORS'
            )
            
            # Restore original active
            if original_active:
                mesh.color_attributes.active_color = original_active
                
        except Exception as e:
            self.report({'WARNING'}, f"Combined bake failed: {str(e)}. Using fallback.")
            # Fallback to texture sampling
            self.bake_texture_mode(obj, vcol_layer, obj.active_material, settings)
        
        finally:
            # Restore original render engine
            context.scene.render.engine = original_engine

    def sample_material_at_uv(self, material, uv, bake_mode):
        """Sample material color at UV coordinate based on bake mode"""
        if not material or not material.use_nodes:
            return (1.0, 1.0, 1.0, 1.0)
        
        principled = None
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                principled = node
                break
        
        if not principled:
            return (1.0, 1.0, 1.0, 1.0)
        
        # Sample based on bake mode
        if bake_mode == 'EMIT':
            # Sample emission
            emission_input = principled.inputs.get('Emission Color') or principled.inputs.get('Emission')
            if emission_input and emission_input.is_linked:
                linked_node = emission_input.links[0].from_node
                if linked_node.type == 'TEX_IMAGE' and linked_node.image:
                    color, alpha = self.sample_image_at_uv(linked_node.image, uv)
                    if color:
                        # Multiply by emission strength
                        strength_input = principled.inputs.get('Emission Strength')
                        strength = strength_input.default_value if strength_input else 1.0
                        return (color[0] * strength, color[1] * strength, color[2] * strength, alpha)
            
            # Fallback to default emission
            if emission_input:
                emission_color = emission_input.default_value
                return tuple(emission_color)
            return (0.0, 0.0, 0.0, 1.0)
        
        else:  # DIFFUSE mode
            # Sample base color
            base_color_input = principled.inputs['Base Color']
            if base_color_input.is_linked:
                linked_node = base_color_input.links[0].from_node
                
                if linked_node.type == 'TEX_IMAGE' and linked_node.image:
                    color, alpha = self.sample_image_at_uv(linked_node.image, uv)
                    if color:
                        return (*color, alpha)
            
            # Fallback to default value
            base_color = base_color_input.default_value
            return tuple(base_color)

    def get_material_color_by_mode(self, material, bake_mode):
        """Get material color based on bake mode (for objects without UVs)"""
        if not material or not material.use_nodes:
            return (1.0, 1.0, 1.0, 1.0)
        
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                if bake_mode == 'EMIT':
                    emission_input = node.inputs.get('Emission Color') or node.inputs.get('Emission')
                    if emission_input:
                        emission = emission_input.default_value
                        strength_input = node.inputs.get('Emission Strength')
                        strength = strength_input.default_value if strength_input else 1.0
                        return (emission[0] * strength, emission[1] * strength, emission[2] * strength, 1.0)
                    return (0.0, 0.0, 0.0, 1.0)
                else:  # DIFFUSE
                    return tuple(node.inputs['Base Color'].default_value)
        
        return (1.0, 1.0, 1.0, 1.0)

    def sample_image_at_uv(self, image, uv_coord):
        """Sample an image at UV coordinates"""
        if not image or not image.pixels:
            return None, None
        
        width = image.size[0]
        height = image.size[1]
        
        # Wrap UV coordinates
        u = uv_coord[0] % 1.0
        v = uv_coord[1] % 1.0
        
        # Convert to pixel coordinates
        x = int(u * width) % width
        y = int(v * height) % height
        
        pixel_index = (y * width + x) * 4
        
        try:
            r = image.pixels[pixel_index]
            g = image.pixels[pixel_index + 1]
            b = image.pixels[pixel_index + 2]
            a = image.pixels[pixel_index + 3]
            return [r, g, b], a
        except IndexError:
            return None, None


class GaussianSplatExporter(bpy.types.Operator, ExportHelper):
    """Export mesh to Gaussian Splat format"""
    bl_idname = "export_scene.gaussian_splat"
    bl_label = "Export Gaussian Splat"

    filename_ext = ".ply"

    filter_glob: StringProperty(
        default="*.ply",
        options={'HIDDEN'},
    )

    splat_transform_path: StringProperty(
        name="splat-transform Command",
        description="Command to run splat-transform (e.g., 'splat-transform' if globally installed, or full path)",
        default="splat-transform",
    )

    overwrite_output: BoolProperty(
        name="Overwrite Existing File",
        description="Overwrite output file if it exists",
        default=True
    )

    keep_mjs_file: BoolProperty(
        name="Export .mjs File",
        description="Save the .mjs generator file in the export directory",
        default=False
    )

    use_frame_number: BoolProperty(
        name="Use Frame Number in Filename",
        description="Append the current frame number to the exported filename",
        default=False
    )

    batch_export_animation: BoolProperty(
        name="Batch Export Animation",
        description="Export all frames from timeline start to end",
        default=False
    )

    sample_density: FloatProperty(
        name="Sample Density",
        description="Number of splats per square unit (only used in Surface Sampling mode)",
        default=100.0,
        min=1.0,
        max=10000.0
    )

    sampling_mode: EnumProperty(
        name="Sampling Mode",
        description="How to generate splats from the mesh",
        items=(
            ('VERTICES', "Use Vertices", "Create one splat per vertex"),
            ('SURFACE', "Surface Sampling", "Sample splats across surface area"),
        ),
        default='VERTICES',
    )

    splat_scale: FloatProperty(
        name="Global Scale Multiplier",
        description="Global scale multiplier applied to all splats (multiplied with auto-calculated size based on vertex proximity)",
        default=1.0,
        min=0.001,
        max=1000.0
    )
    
    use_auto_scale: BoolProperty(
        name="Auto Scale from Vertex Proximity",
        description="Automatically scale splats based on distance to nearest vertex",
        default=True
    )

    splat_opacity: FloatProperty(
        name="Global Opacity Multiplier",
        description="Global opacity multiplier applied to all splats (multiplied with color attribute alpha)",
        default=1.0,
        min=0.0,
        max=1.0
    )

    use_vertex_colors: BoolProperty(
        name="Use Vertex Colors",
        description="Use vertex colors if available",
        default=True
    )

    use_normals: BoolProperty(
        name="Orient to Normals",
        description="Orient splats perpendicular to surface normals",
        default=True
    )

    bake_mode: EnumProperty(
        name="Bake Mode",
        description="What to bake from the material",
        items=(
            ('DIFFUSE', "Diffuse", "Bake diffuse color only (Base Color without lighting)"),
            ('EMIT', "Emission", "Bake emission only"),
            ('COMBINED', "Combined", "Bake full render with lighting (slower)"),
            ('VERTEX_ONLY', "Vertex Colors Only", "Don't bake textures, use existing vertex colors"),
        ),
        default='DIFFUSE',
    )
    
    bake_samples: IntProperty(
        name="Bake Samples",
        description="Number of samples for Combined bake mode",
        default=16,
        min=1,
        max=1024
    )

    axis_forward: EnumProperty(
        name="Forward",
        items=(
            ('X', "X Forward", ""),
            ('Y', "Y Forward", ""),
            ('Z', "Z Forward", ""),
            ('-X', "-X Forward", ""),
            ('-Y', "-Y Forward", ""),
            ('-Z', "-Z Forward", ""),
        ),
        default='-Z',
    )

    axis_up: EnumProperty(
        name="Up",
        items=(
            ('X', "X Up", ""),
            ('Y', "Y Up", ""),
            ('Z', "Z Up", ""),
            ('-X', "-X Up", ""),
            ('-Y', "-Y Up", ""),
            ('-Z', "-Z Up", ""),
        ),
        default='Y',
    )

    def draw(self, context):
        """Draw the export options in the file browser"""
        layout = self.layout
        
        layout.prop(self, "splat_transform_path")
        layout.prop(self, "overwrite_output")
        layout.prop(self, "keep_mjs_file")
        
        layout.separator()
        layout.label(text="Animation Export:")
        layout.prop(self, "use_frame_number")
        layout.prop(self, "batch_export_animation")
        if self.batch_export_animation:
            layout.label(text=f"Will export frames {context.scene.frame_start} to {context.scene.frame_end}")
        
        layout.separator()
        layout.label(text="Sampling Options:")
        layout.prop(self, "sampling_mode")
        if self.sampling_mode == 'SURFACE':
            layout.prop(self, "sample_density")
        
        layout.separator()
        layout.label(text="Splat Properties:")
        layout.prop(self, "use_auto_scale")
        layout.prop(self, "splat_scale")
        layout.prop(self, "splat_opacity")
        
        layout.separator()
        layout.label(text="Color Options:")
        layout.prop(self, "use_vertex_colors")
        layout.prop(self, "bake_mode")
        if self.bake_mode == 'COMBINED':
            layout.prop(self, "bake_samples")
            layout.label(text="Note: Requires proper scene lighting", icon='INFO')
        layout.prop(self, "use_normals")
        
        layout.separator()
        layout.label(text="Axis Conversion:")
        layout.prop(self, "axis_forward")
        layout.prop(self, "axis_up")

    def execute(self, context):
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Check if batch export is enabled
        if self.batch_export_animation:
            return self.batch_export_frames(context, selected_objects)
        else:
            return self.export_single_frame(context, selected_objects, context.scene.frame_current)

    def export_single_frame(self, context, selected_objects, frame_number):
        """Export a single frame"""
        # Set the frame
        context.scene.frame_set(frame_number)
        
        # Temporarily bake textures to vertex colors if needed
        temp_vcol_layers = {}
        for obj in selected_objects:
            if obj.active_material and obj.active_material.use_nodes:
                temp_vcol_layers[obj] = self.bake_temp_vertex_colors(obj, context)
        
        # Build filepath with optional frame number
        if self.use_frame_number:
            base_name = os.path.splitext(self.filepath)[0]
            filepath = f"{base_name}_{frame_number:04d}.ply"
        else:
            filepath = self.filepath
        
        export_dir = os.path.dirname(filepath)
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        generator_path = os.path.join(export_dir, f"{base_name}.mjs")

        try:
            axis_matrix = get_axis_conversion_matrix(self)

            all_samples = []
            for obj in selected_objects:
                if self.sampling_mode == 'VERTICES':
                    samples = sample_vertices(obj, context, axis_matrix, self)
                else:
                    samples = sample_mesh(obj, context, axis_matrix, self)
                all_samples.extend(samples)

            self.report({'INFO'}, f"Frame {frame_number}: Sampled {len(all_samples)} points from {len(selected_objects)} object(s)")

            create_mesh_generator(generator_path, all_samples)

            cmd = [self.splat_transform_path]
            if self.overwrite_output:
                cmd.append('-w')
            cmd.extend([generator_path, filepath])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True
            )

            if result.returncode != 0:
                self.report({'ERROR'}, f"splat-transform failed: {result.stderr}")
                return {'CANCELLED'}

            # Delete .mjs file if not keeping it
            if not self.keep_mjs_file and os.path.exists(generator_path):
                try:
                    os.remove(generator_path)
                except Exception as e:
                    self.report({'WARNING'}, f"Could not delete .mjs file: {str(e)}")

            self.report({'INFO'}, f"Successfully exported to {filepath}")
            result_status = {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            result_status = {'CANCELLED'}
        
        finally:
            # Clean up temporary vertex color layers
            for obj, vcol_layer in temp_vcol_layers.items():
                if vcol_layer and vcol_layer.name in obj.data.vertex_colors:
                    obj.data.vertex_colors.remove(vcol_layer)
        
        return result_status

    def batch_export_frames(self, context, selected_objects):
        """Export all frames in the timeline range"""
        start_frame = context.scene.frame_start
        end_frame = context.scene.frame_end
        original_frame = context.scene.frame_current
        
        total_frames = end_frame - start_frame + 1
        self.report({'INFO'}, f"Starting batch export of {total_frames} frames...")
        
        success_count = 0
        fail_count = 0
        
        for frame in range(start_frame, end_frame + 1):
            result = self.export_single_frame(context, selected_objects, frame)
            if result == {'FINISHED'}:
                success_count += 1
            else:
                fail_count += 1
        
        # Restore original frame
        context.scene.frame_set(original_frame)
        
        if fail_count == 0:
            self.report({'INFO'}, f"Batch export complete! Successfully exported {success_count} frames.")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"Batch export finished with errors. Success: {success_count}, Failed: {fail_count}")
            return {'FINISHED'}

    def bake_temp_vertex_colors(self, obj, context):
        """Temporarily bake textures to vertex colors for current frame"""
        mesh = obj.data
        material = obj.active_material
        
        # Skip baking if mode is vertex colors only
        if self.bake_mode == 'VERTEX_ONLY':
            return None
        
        # Check if material has any texture connections
        has_textures = False
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    if node.inputs['Base Color'].is_linked or (node.inputs.get('Emission Color') and node.inputs.get('Emission Color').is_linked):
                        has_textures = True
                        break
        
        if not has_textures and self.bake_mode != 'COMBINED':
            return None
        
        # Create temporary vertex color layer
        temp_name = "_temp_bake_"
        if temp_name in mesh.vertex_colors:
            vcol_layer = mesh.vertex_colors[temp_name]
        else:
            vcol_layer = mesh.vertex_colors.new(name=temp_name)
        
        # Set as active so it gets picked up during export
        mesh.vertex_colors.active = vcol_layer
        
        # Use appropriate baking method based on mode
        if self.bake_mode == 'COMBINED':
            # Use Blender's built-in bake system for full lighting
            self.bake_combined_mode(obj, vcol_layer, context)
        else:
            # Use direct texture sampling for diffuse/emission
            self.bake_texture_mode(obj, vcol_layer, material)
        
        return vcol_layer

    def bake_texture_mode(self, obj, vcol_layer, material):
        """Bake textures directly by sampling (fast, no lighting)"""
        mesh = obj.data
        
        if not mesh.uv_layers.active:
            # No UVs, use material base color
            color = self.get_material_color_by_mode(material, self.bake_mode)
            for poly in mesh.polygons:
                for loop_idx in poly.loop_indices:
                    vcol_layer.data[loop_idx].color = color
            return
        
        uv_layer = mesh.uv_layers.active
        
        # Sample texture for each loop
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                loop = mesh.loops[loop_idx]
                uv = uv_layer.data[loop_idx].uv
                
                color = self.sample_material_at_uv(material, uv, self.bake_mode)
                vcol_layer.data[loop_idx].color = color

    def bake_combined_mode(self, obj, vcol_layer, context):
        """Bake using Blender's render bake system (includes lighting)"""
        # Store original settings
        original_engine = context.scene.render.engine
        
        try:
            # Set up for baking
            context.scene.render.engine = 'CYCLES'
            context.scene.cycles.samples = self.bake_samples
            
            # Ensure the object is selected
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            
            # Store original active color attribute
            mesh = obj.data
            original_active = mesh.color_attributes.active_color if hasattr(mesh, 'color_attributes') else None
            
            # Set our temp layer as active for baking
            if hasattr(mesh, 'color_attributes'):
                for attr in mesh.color_attributes:
                    if attr.name == vcol_layer.name:
                        mesh.color_attributes.active_color = attr
                        break
            
            # Perform the bake
            bpy.ops.object.bake(
                type='COMBINED',
                use_selected_to_active=False,
                target='VERTEX_COLORS'
            )
            
            # Restore original active
            if original_active:
                mesh.color_attributes.active_color = original_active
                
        except Exception as e:
            self.report({'WARNING'}, f"Combined bake failed: {str(e)}. Using fallback.")
            # Fallback to texture sampling
            self.bake_texture_mode(obj, vcol_layer, obj.active_material)
        
        finally:
            # Restore original render engine
            context.scene.render.engine = original_engine

    def sample_material_at_uv(self, material, uv, bake_mode):
        """Sample material color at UV coordinate based on bake mode"""
        if not material or not material.use_nodes:
            return (1.0, 1.0, 1.0, 1.0)
        
        principled = None
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                principled = node
                break
        
        if not principled:
            return (1.0, 1.0, 1.0, 1.0)
        
        # Sample based on bake mode
        if bake_mode == 'EMIT':
            # Sample emission
            emission_input = principled.inputs.get('Emission Color') or principled.inputs.get('Emission')
            if emission_input and emission_input.is_linked:
                linked_node = emission_input.links[0].from_node
                if linked_node.type == 'TEX_IMAGE' and linked_node.image:
                    color, alpha = self.sample_image_at_uv(linked_node.image, uv)
                    if color:
                        # Multiply by emission strength
                        strength_input = principled.inputs.get('Emission Strength')
                        strength = strength_input.default_value if strength_input else 1.0
                        return (color[0] * strength, color[1] * strength, color[2] * strength, alpha)
            
            # Fallback to default emission
            if emission_input:
                emission_color = emission_input.default_value
                return tuple(emission_color)
            return (0.0, 0.0, 0.0, 1.0)
        
        else:  # DIFFUSE mode
            # Sample base color
            base_color_input = principled.inputs['Base Color']
            if base_color_input.is_linked:
                linked_node = base_color_input.links[0].from_node
                
                if linked_node.type == 'TEX_IMAGE' and linked_node.image:
                    color, alpha = self.sample_image_at_uv(linked_node.image, uv)
                    if color:
                        return (*color, alpha)
            
            # Fallback to default value
            base_color = base_color_input.default_value
            return tuple(base_color)

    def get_material_color_by_mode(self, material, bake_mode):
        """Get material color based on bake mode (for objects without UVs)"""
        if not material or not material.use_nodes:
            return (1.0, 1.0, 1.0, 1.0)
        
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                if bake_mode == 'EMIT':
                    emission_input = node.inputs.get('Emission Color') or node.inputs.get('Emission')
                    if emission_input:
                        emission = emission_input.default_value
                        strength_input = node.inputs.get('Emission Strength')
                        strength = strength_input.default_value if strength_input else 1.0
                        return (emission[0] * strength, emission[1] * strength, emission[2] * strength, 1.0)
                    return (0.0, 0.0, 0.0, 1.0)
                else:  # DIFFUSE
                    return tuple(node.inputs['Base Color'].default_value)
        
        return (1.0, 1.0, 1.0, 1.0)

    def sample_image_at_uv(self, image, uv_coord):
        """Sample an image at UV coordinates"""
        if not image or not image.pixels:
            return None, None
        
        width = image.size[0]
        height = image.size[1]
        
        # Wrap UV coordinates
        u = uv_coord[0] % 1.0
        v = uv_coord[1] % 1.0
        
        # Convert to pixel coordinates
        x = int(u * width) % width
        y = int(v * height) % height
        
        pixel_index = (y * width + x) * 4
        
        try:
            r = image.pixels[pixel_index]
            g = image.pixels[pixel_index + 1]
            b = image.pixels[pixel_index + 2]
            a = image.pixels[pixel_index + 3]
            return [r, g, b], a
        except IndexError:
            return None, None


# Shared utility functions
def get_axis_conversion_matrix(settings):
    """Create a conversion matrix based on axis settings"""
    from bpy_extras.io_utils import axis_conversion

    conv_matrix = axis_conversion(
        from_forward='-Y',
        from_up='Z',
        to_forward=settings.axis_forward,
        to_up=settings.axis_up,
    ).to_4x4()

    return conv_matrix


def sample_vertices(obj, context, axis_matrix, settings):
    """Create splats directly from mesh vertices"""
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()

    matrix_world = axis_matrix @ obj.matrix_world
    material = obj.active_material
    
    color_attribute = None
    has_vertex_colors = False
    
    if hasattr(mesh, 'color_attributes') and len(mesh.color_attributes) > 0:
        color_attribute = mesh.color_attributes.active_color
        if color_attribute:
            has_vertex_colors = True
    elif hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
        color_attribute = mesh.vertex_colors.active
        has_vertex_colors = True

    # Build KD-tree for nearest neighbor searches if auto-scale is enabled
    kd = None
    if settings.use_auto_scale:
        from mathutils import kdtree
        kd = kdtree.KDTree(len(mesh.vertices))
        for i, v in enumerate(mesh.vertices):
            kd.insert(v.co, i)
        kd.balance()

    samples = []

    for vert in mesh.vertices:
        world_pos = matrix_world @ vert.co
        color, alpha = get_vertex_color(vert.index, mesh, has_vertex_colors, color_attribute, material, settings)
        normal = matrix_world.to_3x3() @ vert.normal if settings.use_normals else Vector((0, 0, 1))
        
        # Calculate scale based on nearest neighbor distance
        if settings.use_auto_scale and kd:
            # Find the 2 nearest vertices (first will be the vertex itself)
            nearest = kd.find_n(vert.co, 2)
            if len(nearest) > 1:
                nearest_dist = nearest[1][2]  # Distance to second nearest (first is self at distance 0)
                # Ensure minimum scale to prevent log(0) errors
                auto_scale = max(nearest_dist, 0.0001)
            else:
                auto_scale = settings.splat_scale
            final_scale = auto_scale * settings.splat_scale
        else:
            final_scale = settings.splat_scale
        
        # Ensure final_scale is always positive and non-zero
        final_scale = max(final_scale, 0.0001)
        
        # Multiply alpha with global opacity
        final_opacity = alpha * settings.splat_opacity

        samples.append({
            'position': world_pos,
            'color': color,
            'normal': normal,
            'scale': final_scale,
            'opacity': final_opacity
        })

    obj_eval.to_mesh_clear()
    return samples


def sample_mesh(obj, context, axis_matrix, settings):
    """Sample points from mesh surface"""
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()

    matrix_world = axis_matrix @ obj.matrix_world
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    material = obj.active_material
    
    color_attribute = None
    has_vertex_colors = False
    
    if hasattr(mesh, 'color_attributes') and len(mesh.color_attributes) > 0:
        color_attribute = mesh.color_attributes.active_color
        if color_attribute:
            has_vertex_colors = True
    elif hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
        color_attribute = mesh.vertex_colors.active
        has_vertex_colors = True

    # Build KD-tree for nearest neighbor searches if auto-scale is enabled
    kd = None
    if settings.use_auto_scale:
        from mathutils import kdtree
        kd = kdtree.KDTree(len(mesh.vertices))
        for i, v in enumerate(mesh.vertices):
            kd.insert(v.co, i)
        kd.balance()

    samples = []

    total_area = sum(face.calc_area() for face in bm.faces)
    num_samples = int(total_area * settings.sample_density)

    for face in bm.faces:
        face_area = face.calc_area()
        face_samples = max(1, int((face_area / total_area) * num_samples))

        for _ in range(face_samples):
            r1 = math.sqrt(bpy.context.scene.frame_current * 0.001 + len(samples) * 0.1) % 1.0
            r2 = (len(samples) * 0.7) % 1.0
            if r1 + r2 > 1:
                r1 = 1 - r1
                r2 = 1 - r2

            v0, v1, v2 = [v.co for v in face.verts[:3]]
            pos = v0 + (v1 - v0) * r1 + (v2 - v0) * r2
            world_pos = matrix_world @ pos

            color, alpha = get_face_color(face, obj, mesh, has_vertex_colors, color_attribute, material, settings)
            normal = matrix_world.to_3x3() @ face.normal if settings.use_normals else Vector((0, 0, 1))
            
            # Calculate scale based on nearest vertex distance
            if settings.use_auto_scale and kd:
                nearest = kd.find(pos)
                if nearest:
                    # Ensure minimum scale to prevent log(0) errors
                    auto_scale = max(nearest[2], 0.0001)  # Distance to nearest vertex
                else:
                    auto_scale = settings.splat_scale
                final_scale = auto_scale * settings.splat_scale
            else:
                final_scale = settings.splat_scale
            
            # Ensure final_scale is always positive and non-zero
            final_scale = max(final_scale, 0.0001)
            
            # Multiply alpha with global opacity
            final_opacity = alpha * settings.splat_opacity

            samples.append({
                'position': world_pos,
                'color': color,
                'normal': normal,
                'scale': final_scale,
                'opacity': final_opacity
            })

    bm.free()
    obj_eval.to_mesh_clear()

    return samples


def get_face_color(face, obj, mesh, has_vertex_colors, color_attribute, material, settings):
    """Get color and alpha for a face"""
    if settings.use_vertex_colors and has_vertex_colors and color_attribute:
        try:
            colors = []
            alphas = []
            
            if hasattr(color_attribute, 'domain'):
                domain = color_attribute.domain
                
                if domain == 'CORNER':
                    for loop in face.loops:
                        mesh_loop_index = loop.index
                        if mesh_loop_index < len(color_attribute.data):
                            color_data = color_attribute.data[mesh_loop_index].color
                            colors.append(color_data[:3])
                            # Get alpha (4th component)
                            alphas.append(color_data[3] if len(color_data) > 3 else 1.0)
                
                elif domain == 'POINT':
                    for vert in face.verts:
                        vert_index = vert.index
                        if vert_index < len(color_attribute.data):
                            color_data = color_attribute.data[vert_index].color
                            colors.append(color_data[:3])
                            alphas.append(color_data[3] if len(color_data) > 3 else 1.0)
                
                elif domain == 'FACE':
                    face_index = face.index
                    if face_index < len(color_attribute.data):
                        color_data = color_attribute.data[face_index].color
                        alpha = color_data[3] if len(color_data) > 3 else 1.0
                        return list(color_data[:3]), alpha
            
            else:
                for loop_elem in mesh.loops:
                    for loop in face.loops:
                        if loop.index == loop_elem.index:
                            if loop_elem.index < len(color_attribute.data):
                                color_data = color_attribute.data[loop_elem.index].color
                                colors.append(color_data[:3])
                                alphas.append(color_data[3] if len(color_data) > 3 else 1.0)
                            break
            
            if colors:
                avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                avg_alpha = sum(alphas) / len(alphas) if alphas else 1.0
                return avg_color, avg_alpha
                
        except (IndexError, AttributeError):
            pass

    if material and material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                base_color = node.inputs['Base Color'].default_value
                alpha = base_color[3] if len(base_color) > 3 else 1.0
                return list(base_color[:3]), alpha

    return [1.0, 1.0, 1.0], 1.0


def get_vertex_color(vert_index, mesh, has_vertex_colors, color_attribute, material, settings):
    """Get color and alpha for a specific vertex"""
    if settings.use_vertex_colors and has_vertex_colors and color_attribute:
        try:
            if hasattr(color_attribute, 'domain'):
                domain = color_attribute.domain
                
                if domain == 'POINT':
                    if vert_index < len(color_attribute.data):
                        color_data = color_attribute.data[vert_index].color
                        alpha = color_data[3] if len(color_data) > 3 else 1.0
                        return list(color_data[:3]), alpha
                
                elif domain == 'CORNER':
                    colors = []
                    alphas = []
                    for loop in mesh.loops:
                        if loop.vertex_index == vert_index:
                            if loop.index < len(color_attribute.data):
                                color_data = color_attribute.data[loop.index].color
                                colors.append(color_data[:3])
                                alphas.append(color_data[3] if len(color_data) > 3 else 1.0)
                    if colors:
                        avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                        avg_alpha = sum(alphas) / len(alphas) if alphas else 1.0
                        return avg_color, avg_alpha
                
                elif domain == 'FACE':
                    colors = []
                    alphas = []
                    for poly in mesh.polygons:
                        if vert_index in poly.vertices:
                            if poly.index < len(color_attribute.data):
                                color_data = color_attribute.data[poly.index].color
                                colors.append(color_data[:3])
                                alphas.append(color_data[3] if len(color_data) > 3 else 1.0)
                    if colors:
                        avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                        avg_alpha = sum(alphas) / len(alphas) if alphas else 1.0
                        return avg_color, avg_alpha
                
        except (IndexError, AttributeError):
            pass

    if material and material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                base_color = node.inputs['Base Color'].default_value
                alpha = base_color[3] if len(base_color) > 3 else 1.0
                return list(base_color[:3]), alpha

    return [1.0, 1.0, 1.0], 1.0


def create_mesh_generator(path, samples):
    """Create a generator file for splat-transform"""
    def normal_to_quat(normal):
        up = Vector((0, 0, 1))
        if abs(normal.dot(up)) > 0.999:
            return [0, 0, 0, 1]
        axis = up.cross(normal).normalized()
        angle = math.acos(up.dot(normal))
        half_angle = angle / 2
        s = math.sin(half_angle)
        return [axis.x * s, axis.y * s, axis.z * s, math.cos(half_angle)]

    SH_C0 = 0.28209479177387814

    sample_data = []
    for sample in samples:
        pos = sample['position']
        color = sample['color']
        scale = math.log(sample['scale'])
        opacity = sample['opacity']
        quat = normal_to_quat(sample['normal'])
        sample_str = (
            f"[{pos.x:.6f}, {pos.y:.6f}, {pos.z:.6f}, "
            f"{scale:.6f}, {color[0]:.6f}, {color[1]:.6f}, {color[2]:.6f}, {opacity:.6f}, "
            f"{quat[0]:.6f}, {quat[1]:.6f}, {quat[2]:.6f}, {quat[3]:.6f}]"
        )
        sample_data.append(sample_str)

    samples_joined = ',\n            '.join(sample_data)

    code = f"""class Generator {{
    constructor() {{
        this.count = {len(samples)};
        
        this.columnNames = [
            'x', 'y', 'z',
            'scale_0', 'scale_1', 'scale_2',
            'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity',
            'rot_0', 'rot_1', 'rot_2', 'rot_3'
        ];
        
        const SH_C0 = {SH_C0};
        const packClr = (c) => (c - 0.5) / SH_C0;
        const packOpacity = (opacity) => (opacity <= 0) ? -20 : (opacity >= 1) ? 20 : -Math.log(1 / opacity - 1);
        
        const samples = [
            {samples_joined}
        ];
        
        this.getRow = (index, row) => {{
            const s = samples[index];
            row.x = s[0];
            row.y = s[1];
            row.z = s[2];
            row.scale_0 = s[3];
            row.scale_1 = s[3];
            row.scale_2 = s[3];
            row.f_dc_0 = packClr(s[4]);
            row.f_dc_1 = packClr(s[5]);
            row.f_dc_2 = packClr(s[6]);
            row.opacity = packOpacity(s[7]);
            row.rot_0 = s[8];
            row.rot_1 = s[9];
            row.rot_2 = s[10];
            row.rot_3 = s[11];
        }};
    }}
    static create(params) {{
        return new Generator();
    }}
}}
export {{ Generator }};
"""

    with open(path, 'w') as f:
        f.write(code)


def menu_func_export(self, context):
    self.layout.operator(GaussianSplatExporter.bl_idname, text="Gaussian Splat (.ply)")


# Registration
classes = (
    GaussianSplatSettings,
    GAUSSIANSPLAT_PT_MainPanel,
    GAUSSIANSPLAT_OT_DirectExport,
    GaussianSplatExporter,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.gaussian_splat_settings = PointerProperty(type=GaussianSplatSettings)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    
    del bpy.types.Scene.gaussian_splat_settings
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
