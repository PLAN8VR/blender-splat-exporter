bl_info = {
    "name": "Gaussian Splat Exporter",
    "author": "PLAN8",
    "version": (0, 0, 7),
    "blender": (3, 0, 0),
    "location": "File > Export > Gaussian Splat (.ply)",
    "description": "Export mesh geometry to Gaussian Splat format using Playcanvas' splat-transform",
    "category": "Import-Export",
}

import bpy
import bmesh
import json
import os
import subprocess
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty, EnumProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector, Matrix
import math


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
        name="Splat Scale",
        description="Size of individual splats",
        default=0.05,
        min=0.001,
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

    def get_axis_conversion_matrix(self):
        """Create a conversion matrix based on axis settings"""
        from bpy_extras.io_utils import axis_conversion

        conv_matrix = axis_conversion(
            from_forward='-Y',  # Blender's default forward
            from_up='Z',        # Blender's default up
            to_forward=self.axis_forward,
            to_up=self.axis_up,
        ).to_4x4()

        return conv_matrix

    def execute(self, context):
        # Get selected objects
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Derive output directory and .mjs filename (same as .ply)
        export_dir = os.path.dirname(self.filepath)
        base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        generator_path = os.path.join(export_dir, f"{base_name}.mjs")

        try:
            # Get axis conversion matrix
            axis_matrix = self.get_axis_conversion_matrix()

            # Sample points from meshes
            all_samples = []
            for obj in selected_objects:
                if self.sampling_mode == 'VERTICES':
                    samples = self.sample_vertices(obj, context, axis_matrix)
                else:
                    samples = self.sample_mesh(obj, context, axis_matrix)
                all_samples.extend(samples)

            self.report({'INFO'}, f"Sampled {len(all_samples)} points from {len(selected_objects)} object(s)")

            # Generate the mesh generator file
            self.create_mesh_generator(generator_path, all_samples)

            # Build splat-transform command as a list
            cmd = [self.splat_transform_path]
            if self.overwrite_output:
                cmd.append('-w')
            cmd.extend([generator_path, self.filepath])
            
            self.report({'INFO'}, f"Running: {' '.join(cmd)}")

            # Run splat-transform
            # On Windows, shell=True is needed if splat_transform_path is just a command name
            # but we need to pass cmd as a list for proper argument handling
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True
            )

            if result.returncode != 0:
                self.report({'ERROR'}, f"splat-transform failed: {result.stderr}")
                return {'CANCELLED'}

            self.report({'INFO'}, f"Successfully exported to {self.filepath}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}

    def sample_vertices(self, obj, context, axis_matrix):
        """Create splats directly from mesh vertices"""
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()

        matrix_world = axis_matrix @ obj.matrix_world
        
        material = obj.active_material
        
        # Check for color attributes (new system) or vertex colors (legacy)
        color_attribute = None
        has_vertex_colors = False
        
        if hasattr(mesh, 'color_attributes') and len(mesh.color_attributes) > 0:
            color_attribute = mesh.color_attributes.active_color
            if color_attribute:
                has_vertex_colors = True
        elif hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
            color_attribute = mesh.vertex_colors.active
            has_vertex_colors = True

        samples = []

        # Process each vertex
        for vert in mesh.vertices:
            world_pos = matrix_world @ vert.co
            
            # Get vertex color if available
            color = self.get_vertex_color(vert.index, mesh, has_vertex_colors, color_attribute, material)
            
            # Use vertex normal
            normal = matrix_world.to_3x3() @ vert.normal if self.use_normals else Vector((0, 0, 1))

            samples.append({
                'position': world_pos,
                'color': color,
                'normal': normal,
                'scale': self.splat_scale
            })

        obj_eval.to_mesh_clear()
        return samples

    def sample_mesh(self, obj, context, axis_matrix):
        """Sample points from mesh surface"""
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()

        matrix_world = axis_matrix @ obj.matrix_world
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()

        material = obj.active_material
        
        # Check for color attributes (new system) or vertex colors (legacy)
        color_attribute = None
        has_vertex_colors = False
        
        if hasattr(mesh, 'color_attributes') and len(mesh.color_attributes) > 0:
            # Try to get the active color attribute
            color_attribute = mesh.color_attributes.active_color
            if color_attribute:
                has_vertex_colors = True
        elif hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
            # Fallback to legacy vertex colors
            color_attribute = mesh.vertex_colors.active
            has_vertex_colors = True

        samples = []

        total_area = sum(face.calc_area() for face in bm.faces)
        num_samples = int(total_area * self.sample_density)

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

                color = self.get_face_color(face, obj, mesh, has_vertex_colors, color_attribute, material)
                normal = matrix_world.to_3x3() @ face.normal if self.use_normals else Vector((0, 0, 1))

                samples.append({
                    'position': world_pos,
                    'color': color,
                    'normal': normal,
                    'scale': self.splat_scale
                })

        bm.free()
        obj_eval.to_mesh_clear()

        return samples

    def get_face_color(self, face, obj, mesh, has_vertex_colors, color_attribute, material):
        """Get color for a face"""
        if self.use_vertex_colors and has_vertex_colors and color_attribute:
            try:
                colors = []
                
                # Check the domain of the color attribute
                if hasattr(color_attribute, 'domain'):
                    domain = color_attribute.domain
                    
                    if domain == 'CORNER':
                        # Face corner colors - use loop indices directly from the mesh
                        for loop in face.loops:
                            mesh_loop_index = loop.index
                            if mesh_loop_index < len(color_attribute.data):
                                color_data = color_attribute.data[mesh_loop_index].color
                                colors.append(color_data[:3])
                    
                    elif domain == 'POINT':
                        # Vertex colors - use vertex indices
                        for vert in face.verts:
                            vert_index = vert.index
                            if vert_index < len(color_attribute.data):
                                color_data = color_attribute.data[vert_index].color
                                colors.append(color_data[:3])
                    
                    elif domain == 'FACE':
                        # Face colors - use face index
                        face_index = face.index
                        if face_index < len(color_attribute.data):
                            color_data = color_attribute.data[face_index].color
                            return list(color_data[:3])
                
                else:
                    # Legacy vertex colors - use mesh loop indices
                    for loop_elem in mesh.loops:
                        for loop in face.loops:
                            if loop.index == loop_elem.index:
                                if loop_elem.index < len(color_attribute.data):
                                    color_data = color_attribute.data[loop_elem.index].color
                                    colors.append(color_data[:3])
                                break
                
                # Average the colors if we got any
                if colors:
                    avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                    return avg_color
                    
            except (IndexError, AttributeError) as e:
                # If there's any issue reading color attributes, fall through to material color
                pass

        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    base_color = node.inputs['Base Color'].default_value[:3]
                    return list(base_color)

        return [1.0, 1.0, 1.0]

    def get_vertex_color(self, vert_index, mesh, has_vertex_colors, color_attribute, material):
        """Get color for a specific vertex"""
        if self.use_vertex_colors and has_vertex_colors and color_attribute:
            try:
                # Check the domain of the color attribute
                if hasattr(color_attribute, 'domain'):
                    domain = color_attribute.domain
                    
                    if domain == 'POINT':
                        # Vertex colors - direct access
                        if vert_index < len(color_attribute.data):
                            color_data = color_attribute.data[vert_index].color
                            return list(color_data[:3])
                    
                    elif domain == 'CORNER':
                        # Face corner colors - average all corners connected to this vertex
                        colors = []
                        for loop in mesh.loops:
                            if loop.vertex_index == vert_index:
                                if loop.index < len(color_attribute.data):
                                    color_data = color_attribute.data[loop.index].color
                                    colors.append(color_data[:3])
                        
                        if colors:
                            avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                            return avg_color
                    
                    elif domain == 'FACE':
                        # Face colors - average all faces connected to this vertex
                        colors = []
                        for poly in mesh.polygons:
                            if vert_index in poly.vertices:
                                if poly.index < len(color_attribute.data):
                                    color_data = color_attribute.data[poly.index].color
                                    colors.append(color_data[:3])
                        
                        if colors:
                            avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
                            return avg_color
                    
            except (IndexError, AttributeError) as e:
                # If there's any issue reading color attributes, fall through to material color
                pass

        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    base_color = node.inputs['Base Color'].default_value[:3]
                    return list(base_color)

        return [1.0, 1.0, 1.0]

    def create_mesh_generator(self, path, samples):
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
            quat = normal_to_quat(sample['normal'])
            sample_str = (
                f"[{pos.x:.6f}, {pos.y:.6f}, {pos.z:.6f}, "
                f"{scale:.6f}, {color[0]:.6f}, {color[1]:.6f}, {color[2]:.6f}, "
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
            row.opacity = packOpacity(1.0);
            row.rot_0 = s[7];
            row.rot_1 = s[8];
            row.rot_2 = s[9];
            row.rot_3 = s[10];
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


def register():
    bpy.utils.register_class(GaussianSplatExporter)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(GaussianSplatExporter)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == "__main__":
    register()
