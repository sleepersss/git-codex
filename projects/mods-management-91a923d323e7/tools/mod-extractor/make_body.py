"""Blender worker; selection is an explicit local profile, never guessed anatomy."""
import bpy,sys,json,numpy as np
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve()
job=json.loads((run/'job.json').read_text(encoding='utf-8'))
decision=json.loads((run/'body-decision.json').read_text(encoding='utf-8'))
if decision['status']!='eligible':
    raise RuntimeError('Body extraction abandoned: '+decision['reason_code'])
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
all_objects=[o for o in bpy.data.objects if o.type=='MESH']
if job['name']=='denia':
    chosen=[o for o in all_objects if o['SourceGroup']=='ib0' and o['SourceComponent']==3 and json.loads(o['SourceDraw'])['start'] in (492672,558684,668856,754536)]
    profile={'name':'Denia neutral baseline','source_manifest_sha256':job['source_manifest_sha256'],
             'body_draws':[[json.loads(o['SourceDraw'])['count'],json.loads(o['SourceDraw'])['start']] for o in chosen],
             'missing_parts':['head and hair omitted from standalone body'],'completeness':'partial',
             'evidence':'Original labelled Body, Body_EX1, Body_Hands, Body_Feet; body_variant=0; visual review of four source ranges'}
else:
    obj=next(o for o in all_objects if o['SourceComponent']==3)
    islands=json.loads((run/'islands.json').read_text(encoding='utf-8'))
    ids=[3,4,5,13,14]
    selected=set(v for part in islands if part['id'] in ids for v in part['vertices'])
    for o in all_objects:o.select_set(False)
    obj.hide_set(False);obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.context.tool_settings.mesh_select_mode=(False,False,True)
    faces=[p for p in obj.data.polygons if all(v in selected for v in p.vertices)]
    for v in obj.data.vertices:v.select=False
    for e in obj.data.edges:e.select=False
    for p in obj.data.polygons:p.select=p in faces
    before=set(bpy.data.objects)
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.separate(type='SELECTED');bpy.ops.object.mode_set(mode='OBJECT')
    chosen=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
    assert len(chosen)==1
    chosen[0].name='Iuno_partial_skin_body'
    profile={'name':'Iuno reviewed skin islands','source_manifest_sha256':job['source_manifest_sha256'],
             'component':3,'island_ids':ids,'completeness':'partial',
             'missing_parts':['head and hair omitted','bare legs and feet not present in selected skin body','arm continuity has gaps; remaining dressed surfaces not fabricated','torso hem and forearm/hand surface classification still needs manual review'],
             'evidence':'Connected torso and forearm/hand candidates separated from component3; standalone socks, shoes, skirt, garters and accessories excluded; mixed connected surfaces may remain; conservative partial candidate classification'}
for obj in list(bpy.data.objects):
    if obj not in chosen:bpy.data.objects.remove(obj,do_unlink=True)
for obj in chosen:obj.hide_set(False);obj.hide_render=False
text=bpy.data.texts.new('BODY_EXTRACTION_NOTES');text.write(json.dumps(profile,ensure_ascii=False,indent=2))
bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=False,do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=str(run/'models/body.blend'))
bpy.ops.wm.open_mainfile(filepath=str(run/'models/body.blend'))
profile['save_reload_verified']=True
profile['meshes']=[{'name':o.name,'vertices':len(o.data.vertices),'triangles':len(o.data.polygons),
                   'uv_layers':len(o.data.uv_layers),'vertex_groups':len(o.vertex_groups),
                   'shape_keys':len(o.data.shape_keys.key_blocks) if o.data.shape_keys else 0} for o in bpy.data.objects if o.type=='MESH']
(run/'body-selection.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
print('BODY_SAVE_RELOAD_VERIFIED',profile['meshes'])
