"""Runs inside Blender on an existing saved file. Never saves a .blend."""
import bpy
import math
import json
import hashlib
import struct
import sys
from pathlib import Path
from mathutils import Vector
from collections import Counter

output = Path(sys.argv[sys.argv.index('--')+1])
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError('场景没有网格')
objects=[]
world_points=[]
preview_only='--preview-only' in sys.argv
inspected=[o for o in meshes if not o.hide_render and not o.hide_get()] if preview_only else meshes
for obj in inspected:
    m=obj.data
    h=hashlib.sha256()
    edges=Counter()
    for vertex in m.vertices:
        if not all(math.isfinite(x) for x in vertex.co):
            raise RuntimeError('顶点含非有限数值')
        h.update(struct.pack('<3f',*vertex.co))
        world_points.append(obj.matrix_world @ vertex.co)
    for face in m.polygons:
        ids=list(face.vertices)
        h.update(struct.pack('<I',len(ids)))
        h.update(struct.pack('<'+'I'*len(ids),*ids))
        for a,b in zip(ids,ids[1:]+ids[:1]):
            edges[tuple(sorted((a,b)))]+=1
    uv_finite=all(math.isfinite(x) for layer in m.uv_layers for loop in layer.data for x in loop.uv)
    if not uv_finite:
        raise RuntimeError('UV 含非有限数值')
    m.calc_loop_triangles()
    objects.append({'name':obj.name,'vertices':len(m.vertices),'triangles':len(m.loop_triangles),
                    'uv_layers':[l.name for l in m.uv_layers], 'uv_finite':uv_finite,
                    'vertex_groups':[g.name for g in obj.vertex_groups],
                    'vertices_with_weights':sum(any(g.weight>0 for g in v.groups) for v in m.vertices),
                    'shape_keys':[k.name for k in m.shape_keys.key_blocks] if m.shape_keys else [],
                    'materials':[s.material.name if s.material else None for s in obj.material_slots],
                    'modifiers':[{'name':a.name,'type':a.type} for a in obj.modifiers],
                    'matrix_world':[list(row) for row in obj.matrix_world],
                    'custom_property_keys':list(obj.keys()), 'hidden_render':obj.hide_render,
                    'boundary_edges':sum(n==1 for n in edges.values()),
                    'nonmanifold_edges':sum(n>2 for n in edges.values()),
                    'mesh_fingerprint':h.hexdigest()})
fingerprint=hashlib.sha256(''.join(sorted(o['mesh_fingerprint'] for o in objects)).encode()).hexdigest()
stats={'blender_version':bpy.app.version_string,'mesh_count':len(inspected),'scene_mesh_count':len(meshes),
       'inspection_scope':'visible_meshes_only' if preview_only else 'all_scene_meshes',
       'vertex_count':sum(o['vertices'] for o in objects),'triangle_count':sum(o['triangles'] for o in objects),
       'has_armature':any(o.type=='ARMATURE' for o in bpy.context.scene.objects),
       'has_weights':any(o['vertices_with_weights'] for o in objects),
       'has_uv':any(o['uv_layers'] for o in objects),'objects':objects,'mesh_fingerprint':fingerprint,
       'fingerprint_scope':'local indexed coordinates and polygon topology; names excluded, pose/transforms not normalized',
       'completeness':'unverified','boundary_note':'开放接口或分件也会产生边界；不能据此自动判断缺失身体',
       'semantic_body_measurements':'not_computed'}
if world_points:
    stats['world_bounds']={'min':[min(p[i] for p in world_points) for i in range(3)],
                           'max':[max(p[i] for p in world_points) for i in range(3)]}
    stats['bounds_note']='预览可见网格包围盒，不是人体部位测量' if preview_only else '全场景网格包围盒；含隐藏物体，不是人体部位测量'
output.mkdir(parents=True,exist_ok=True)
(output/'inspection.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')

if '--previews' in sys.argv:
    # Render visible objects in their stored pose. Do not guess a clothing/body selection.
    scene=bpy.context.scene
    visible=[o for o in meshes if not o.hide_render and not o.hide_get()]
    if not visible: raise RuntimeError('没有可见网格可生成预览')
    for obj in meshes:
        if obj not in visible: obj.hide_render=True
    for obj in list(scene.objects):
        if obj.type in ('LIGHT','CAMERA'):
            bpy.data.objects.remove(obj,do_unlink=True)
    points=[obj.matrix_world @ Vector(corner) for obj in visible for corner in obj.bound_box]
    lower=Vector([min(p[i] for p in points) for i in range(3)])
    upper=Vector([max(p[i] for p in points) for i in range(3)])
    center=(lower+upper)/2
    span=max(upper-lower)
    if span<=0: raise RuntimeError('网格尺寸为零')
    camera_data=bpy.data.cameras.new('LibraryPreview')
    camera=bpy.data.objects.new('LibraryPreview',camera_data); scene.collection.objects.link(camera)
    camera_data.type='ORTHO'; camera_data.ortho_scale=span*1.25; camera_data.clip_end=max(1000,span*10)
    scene.camera=camera
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.light='STUDIO'; scene.display.shading.color_type='SINGLE'
    scene.display.shading.single_color=(0.66,0.71,0.77)
    scene.display.shading.background_type='WORLD'
    if not scene.world: scene.world=bpy.data.worlds.new('LibraryPreviewWorld')
    scene.world.color=(0.05,0.05,0.05)
    scene.render.resolution_x=640; scene.render.resolution_y=640; scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    for name,direction in [('front',(0,-1,0)),('side',(1,0,0)),('back',(0,1,0)),('three_quarter',(1,-1,0.4))]:
        vector=Vector(direction).normalized()
        camera.location=center+vector*span*3
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(output/(name+'.png')); bpy.ops.render.render(write_still=True)
    stats['preview_convention']='Stored pose; Z up; front camera at -Y; unverified semantic orientation; orthographic same scale'
    (output/'inspection.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
