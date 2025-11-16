# blender-splat-exporter
Blender addon (windows) that exports synthetic Gaussian Splat .ply from mesh geometry using Playcanvas' Splat-Transform. Currently works with vertex colours.
Addon also exports the .mjs file for future use/editing with Splat-Transform. 

Dependency - Splat Transform

 https://github.com/playcanvas/splat-transform - install as per instructions 

Install Blender addon (blender_splat_export.py) the usual way.

Ensure the mesh has an active colour attribute assigned and that vertex colours have been baked or created. (Also works with Principled BSDF base colour)

Select mesh to export, file\export\Gaussian Splat (.ply), or use the options in 3D view side panel. 

Currently, there are two options for Points~|~Splats, use the existing vertices
(most stable and predictable), or sample mesh (less stable and not very optimised just yet). 
There is a slider for global opacity and size of splat, and an autosize splats option based on neareast point relative proximity. The transparency value is calculated from the colour attribute alpha channel. 

 






https://github.com/user-attachments/assets/56a91b27-6227-4ba0-b886-c2a449cde0c7

Pure generated gaussian splat - Blender - Splat-Transform
https://youtu.be/UDXoV1NK7TI



https://github.com/user-attachments/assets/6551adbc-ea51-4198-878f-5a49a4330a1b

Supersplat viewer - https://superspl.at/view?id=086ecbc9
