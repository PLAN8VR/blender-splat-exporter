bl_info = {
    "name": "Gaussian Splat Exporter",
    "author": "PLAN8",
    "version": (0, 0, 1),
    "blender": (3, 0, 0),
    "location": "File > Export > Gaussian Splat (.ply)",
    "description": "Export mesh geometry to Gaussian Splat format using Playcanvas' splat-transform https://github.com/playcanvas/splat-transform",
    "category": "Import-Export",
}

import bpy
import bmesh
import json
import os
import subprocess
import tempfile
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector
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
    
    sample_density: FloatProperty(
        name="Sample Density",
        description="Number of splats per square unit",
        default=100.0,
        min=1.0,
        max=10000.0
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
    
    def execute(self, context):
        # Get selected objects
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objects:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        # Create temporary directory for intermediate files
        temp_dir = tempfile.mkdtemp()
        generator_path = os.path.join(temp_dir, "mesh-generator.mjs")
        
        try:
            # Sample points from meshes
            all_samples = []
            
            for obj in selected_objects:
                samples = self.sample_mesh(obj, context)
                all_samples.extend(samples)
            
            self.report({'INFO'}, f"Sampled {len(all_samples)} points from {len(selected_objects)} object(s)")
            
            # Generate the mesh generator file
            self.create_mesh_generator(generator_path, all_samples)
            
            # Build splat-transform command
            # Format: splat-transform gen.mjs output.ply
            cmd = [self.splat_transform_path, generator_path, self.filepath]
            
            self.report({'INFO'}, f"Running: {' '.join(cmd)}")
            
            # Run splat-transform
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True  # Use shell to find commands in PATH
            )
            
            if result.returncode != 0:
                self.report({'ERROR'}, f"splat-transform failed: {result.stderr}")
                return {'CANCELLED'}
            
            self.report({'INFO'}, f"Successfully exported to {self.filepath}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
        
        finally:
            # Clean up temp files
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def sample_mesh(self, obj, context):
        """Sample points from mesh surface"""
        # Get evaluated mesh (with modifiers applied)
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        
        # Transform to world space
        matrix_world = obj.matrix_world
        
        # Create bmesh for easier manipulation
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        
        # Get material/color data
        material = obj.active_material
        has_vertex_colors = len(mesh.vertex_colors) > 0
        
        samples = []
        
        # Calculate total surface area
        total_area = sum(face.calc_area() for face in bm.faces)
        num_samples = int(total_area * self.sample_density)
        
        # Sample points across surface
        for face in bm.faces:
            face_area = face.calc_area()
            face_samples = max(1, int((face_area / total_area) * num_samples))
            
            for _ in range(face_samples):
                # Random barycentric coordinates
                r1 = math.sqrt(bpy.context.scene.frame_current * 0.001 + len(samples) * 0.1) % 1.0
                r2 = (len(samples) * 0.7) % 1.0
                
                if r1 + r2 > 1:
                    r1 = 1 - r1
                    r2 = 1 - r2
                
                # Interpolate position
                v0, v1, v2 = [v.co for v in face.verts[:3]]
                pos = v0 + (v1 - v0) * r1 + (v2 - v0) * r2
                
                # Transform to world space
                world_pos = matrix_world @ pos
                
                # Get color
                color = self.get_face_color(face, obj, mesh, has_vertex_colors, material)
                
                # Get normal for orientation
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
    
    def get_face_color(self, face, obj, mesh, has_vertex_colors, material):
        """Get color for a face"""
        if self.use_vertex_colors and has_vertex_colors:
            # Average vertex colors
            color_layer = mesh.vertex_colors.active
            colors = []
            for loop in face.loops:
                colors.append(color_layer.data[loop.index].color[:3])
            avg_color = [sum(c[i] for c in colors) / len(colors) for i in range(3)]
            return avg_color
        
        elif material and material.use_nodes:
            # Try to get base color from material
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    base_color = node.inputs['Base Color'].default_value[:3]
                    return list(base_color)
        
        # Default white
        return [1.0, 1.0, 1.0]
    
    def create_mesh_generator(self, path, samples):
        """Create a generator file for splat-transform"""
        # Calculate rotation quaternion from normal
        def normal_to_quat(normal):
            """Convert normal vector to rotation quaternion"""
            up = Vector((0, 0, 1))
            if abs(normal.dot(up)) > 0.999:
                return [0, 0, 0, 1]
            
            axis = up.cross(normal).normalized()
            angle = math.acos(up.dot(normal))
            
            half_angle = angle / 2
            s = math.sin(half_angle)
            
            return [
                axis.x * s,
                axis.y * s,
                axis.z * s,
                math.cos(half_angle)
            ]
        
        # Pack color and opacity like in gen-grid.mjs
        SH_C0 = 0.28209479177387814
        
        # Build sample data as proper JS array
        sample_data = []
        for sample in samples:
            pos = sample['position']
            color = sample['color']
            scale = math.log(sample['scale'])
            quat = normal_to_quat(sample['normal'])
            
            # Format as proper JS array with proper number formatting
            sample_str = (
                f"[{pos.x:.6f}, {pos.y:.6f}, {pos.z:.6f}, "
                f"{scale:.6f}, {color[0]:.6f}, {color[1]:.6f}, {color[2]:.6f}, "
                f"{quat[0]:.6f}, {quat[1]:.6f}, {quat[2]:.6f}, {quat[3]:.6f}]"
            )
            sample_data.append(sample_str)
        
        # Join samples with newline and indent
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
        
        // Sample data: [x, y, z, scale, r, g, b, qx, qy, qz, qw]
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
