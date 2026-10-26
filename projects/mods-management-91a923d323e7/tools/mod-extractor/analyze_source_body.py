"""Inspect actual source-selected body; save only when gap checks pass."""
import bpy,sys,json,numpy as np,hashlib,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from body_selection import draw_metadata,source_state_hint,body_draw_metadata
from body_candidates import select_body_candidates,retain_skin_component
from source_controls import load_control_program
from body_geometry import analyze_body
from body_policy import evaluate_body
from mathutils.bvhtree import BVHTree
from mathutils import Vector
run=Path(sys.argv[sys.argv.index('--')+1]).resolve();job=json.loads((run/'job.json').read_text(encoding='utf-8'))
bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
metadata,neutral=draw_metadata(Path(job['main_ini']),include_neutral_state=True);rows=[]
source_hint=source_state_hint(Path(job.get('source','')).name)
full_bounds=None
for obj in bpy.data.objects:
 if obj.type!='MESH':continue
 for corner in obj.bound_box:
  p=obj.matrix_world @ Vector(corner)
  if full_bounds is None:full_bounds=[[float(v),float(v)] for v in p]
  else:
   for i,v in enumerate(p):full_bounds[i][0]=min(full_bounds[i][0],v);full_bounds[i][1]=max(full_bounds[i][1],v)
for obj in bpy.data.objects:
 if obj.type!='MESH':continue
 d=json.loads(obj.get('SourceDraw','{}'));label=d.get('label','')
 meta=metadata.get((d.get('section','').lower(),d.get('count'),d.get('start'),d.get('base',0)),{})
 # Reparse branches from the verified INI; old full-model files may carry older metadata.
 rows.append({'name':obj.name,**body_draw_metadata(d,meta,neutral,source_hint)})
selection=select_body_candidates(rows,load_control_program(job['main_ini']))
selection.update(parts=rows,source_manifest_sha256=job.get('source_manifest_sha256'),
    source_full_sha256=hashlib.sha256((run/'models/full.blend').read_bytes()).hexdigest())
(run/'body-candidates.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
if selection['status']!='selected':
 messages={'ambiguous':'有多个互斥或重叠的身体版本，尚不能确定所需版本。完整 Mod 模型与候选记录已保留。',
    'search_limited':'来源状态组合超出本次检查上限，未凭部分搜索结果生成身体。完整 Mod 模型已保留。',
    'unresolved':'身体标签或运行时条件尚未确认，完整 Mod 模型与候选记录已保留。'}
 evidence={'selection':rows,'chosen':[],'candidate_selection':selection,'regions':{},
    'skin_only':False,'source_manifest_verified':True,'scope':'headless_body'}
 decision=evaluate_body(job['name'],evidence)
 decision.update(reason_code='body_selection_'+selection['status'],message=messages[selection['status']])
 (run/'body-analysis.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 (run/'body-decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
 print('BODY_DECISION',decision['status'],decision['message']);sys.exit(0)
names=selection['selected'];chosen=[bpy.data.objects[n] for n in names]
source_normals={}
for obj in chosen:
 m=obj.data;m.calc_normals_split();ids=np.empty(len(m.vertices),dtype='i4');m.attributes['SourceVertexIndex'].data.foreach_get('value',ids)
 source_normals[obj.name]={tuple(int(ids[m.loops[i].vertex_index]) for i in f.loop_indices):[tuple(m.loops[i].normal) for i in f.loop_indices] for f in m.polygons}
removed=[]
# Small disconnected skin patches are not deleted by size or arm labels.
points=[];faces=[]
owners={};trees={};patch_bounds={};patch_anchor={}
for obj in chosen:
 local=[tuple(obj.matrix_world @ v.co) for v in obj.data.vertices]
 # Supporting skin can be another disconnected patch in the same source draw.
 parent=list(range(len(local)));coordinate_index={}
 def root(i):
  while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
  return i
 for i,p in enumerate(local):
  if p in coordinate_index:parent[root(i)]=root(coordinate_index[p])
  else:coordinate_index[p]=i
 for f in obj.data.polygons:
  for i in f.vertices[1:]:parent[root(i)]=root(f.vertices[0])
 patches={}
 for f in obj.data.polygons:patches.setdefault(root(f.vertices[0]),[]).append(tuple(f.vertices))
 for part,polys in patches.items():
  identity=obj.name+':'+str(part);trees[identity]=BVHTree.FromPolygons(local,polys)
  ids={i for f in polys for i in f};patch_bounds[identity]=[(min(local[v][i] for v in ids),max(local[v][i] for v in ids)) for i in range(3)]
  patch_anchor[identity]=local[polys[0][0]]
  for v in ids:owners.setdefault(local[v],set()).add(identity)
 offset=len(points);points.extend(local);faces.extend([offset+i for i in f.vertices] for f in obj.data.polygons)
seam_measurements=[]
def supported(ps,tolerance):
 distances=[];nearby=[]
 for p in ps:
  matches=[(tree.find_nearest(Vector(p))[3],name) for name,tree in trees.items() if name not in owners[p]]
  matches.sort();nearby.append(matches)
  distances.append(matches[0][0] if matches else 1e30)
 seam_measurements.append({'points':len(ps),'max_distance_to_other_skin_part':max(distances,default=1e30),'mean_distance':sum(distances)/len(distances),'tolerance':tolerance})
 if max(distances,default=1e30)<=tolerance:
  return {'supported':True,'links':[(p,patch_anchor[matches[0][1]]) for p,matches in zip(ps,nearby)]}
 # An open patch ending inside another source skin patch is an overlapping seam.
 # Require spatial containment as well as a close supporting surface.
 overlap_limit=tolerance*2.5
 seam_measurements[-1]['overlap_surface_limit']=overlap_limit
 links=[]
 for p,matches in zip(ps,nearby):
  candidates=[name for distance,name in matches if distance<=overlap_limit and all(lo-tolerance*.05<=p[i]<=hi+tolerance*.05 for i,(lo,hi) in enumerate(patch_bounds[name]))]
  if not candidates:return None
  links.append((p,patch_anchor[candidates[0]]))
 return {'supported':True,'links':links}
neutral_mode=bool(chosen) and all(r.get('neutral_body_state') for r in rows if r['name'] in names)
analysis=analyze_body(points,faces,supported,include_connected_indices=neutral_mode,reference_bounds=full_bounds)
if neutral_mode:
 # Accessories still drawn in the neutral state are physically separate from the skin.
 # Keep only the verified connected source surface, with no vertex movement or new faces.
 connected=set(analysis.pop('connected_vertex_indices',[]));offset=0;retained=[]
 for obj in chosen:
  m=obj.data;row=next(r for r in rows if r['name']==obj.name)
  keep=[f.index for f in m.polygons if retain_skin_component(row,all(offset+i in connected for i in f.vertices))];offset+=len(m.vertices)
  if not keep:continue
  if len(keep)<len(m.polygons):
   bpy.ops.object.select_all(action='DESELECT');obj.hide_set(False);obj.select_set(True);bpy.context.view_layer.objects.active=obj
   bpy.context.tool_settings.mesh_select_mode=(False,False,True);keep=set(keep)
   for v in m.vertices:v.select=False
   for e in m.edges:e.select=False
   for f in m.polygons:f.select=f.index not in keep
   bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.delete(type='FACE');bpy.ops.object.mode_set(mode='OBJECT')
  retained.append(obj)
 chosen=retained;names=[o.name for o in chosen];points=[];faces=[]
 for obj in chosen:
  offset=len(points);points.extend(tuple(obj.matrix_world @ v.co) for v in obj.data.vertices);faces.extend([offset+i for i in f.vertices] for f in obj.data.polygons)
 analysis=analyze_body(points,faces,supported,reference_bounds=full_bounds)
evidence={'selection':rows,'chosen':names,'candidate_selection':selection,'source_subfolder_clothing_off_evidence':source_hint,'excluded_accessories':removed,'neutral_toggle_state':neutral_mode,'geometry':analysis,'regions':analysis.get('regions',{}),'skin_only':bool(chosen),'source_manifest_verified':True,'scope':'headless_body'}
analysis['seam_measurements']=seam_measurements
decision=evaluate_body(job['name'],evidence)
if chosen and analysis['status']=='gaps':decision.update(status='abandoned',reason_code='body_gaps',missing_parts=analysis['missing_parts'],message='源身体存在肢体缺口：'+', '.join(analysis['missing_parts'])+'。已保留 Mod 模型，未补洞。')
if not chosen:decision.update(message='未识别到源配置中的身体分组；保留 Mod 模型，需选择身体部件或补充配置标签。')
(run/'body-analysis.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
(run/'body-decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
if decision['status']=='eligible':
 for obj in chosen:
  m=obj.data;ids=np.empty(len(m.vertices),dtype='i4');m.attributes['SourceVertexIndex'].data.foreach_get('value',ids)
  original=source_normals[obj.name];normals=[]
  if len(m.polygons)==len(original):continue
  for f in m.polygons:
   key=tuple(int(ids[m.loops[i].vertex_index]) for i in f.loop_indices)
   normals.extend(original[key])
  m.use_auto_smooth=True;m.normals_split_custom_set(normals)
 def fingerprint(obj):
  h=hashlib.sha256();m=obj.data
  for attr in sorted(m.attributes,key=lambda a:a.name):
   if attr.data_type=='INT' and attr.domain=='POINT':
    a=np.empty(len(attr.data),dtype='<i4');attr.data.foreach_get('value',a);h.update(attr.name.encode()+a.tobytes())
  a=np.empty(len(m.vertices)*3,dtype='<f4');m.vertices.foreach_get('co',a);h.update(a.tobytes())
  a=np.empty(len(m.loops),dtype='<i4');m.loops.foreach_get('vertex_index',a);h.update(a.tobytes())
  for layer in m.uv_layers:
   a=np.empty(len(layer.data)*2,dtype='<f4');layer.data.foreach_get('uv',a);h.update(layer.name.encode()+a.tobytes())
  for layer in m.vertex_colors:
   a=np.empty(len(layer.data)*4,dtype='<f4');layer.data.foreach_get('color',a);h.update(layer.name.encode()+a.tobytes())
  h.update(json.dumps({'groups':[g.name for g in obj.vertex_groups],'weights':[[(g.group,g.weight) for g in v.groups] for v in m.vertices]},separators=(',',':')).encode())
  if m.shape_keys:
   for key in m.shape_keys.key_blocks:
    a=np.empty(len(key.data)*3,dtype='<f4');key.data.foreach_get('co',a);h.update(key.name.encode()+a.tobytes())
  return h.hexdigest()
 expected={o.name:fingerprint(o) for o in chosen}
 for obj in list(bpy.data.objects):
  if obj not in chosen:bpy.data.objects.remove(obj,do_unlink=True)
 for obj in chosen:obj.hide_set(False);obj.hide_render=False
 bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=False,do_recursive=True)
 bpy.ops.wm.save_as_mainfile(filepath=str(run/'models/body.blend'));bpy.ops.wm.open_mainfile(filepath=str(run/'models/body.blend'))
 assert {o.name:fingerprint(o) for o in bpy.data.objects if o.type=='MESH'}==expected
 (run/'body-selection.json').write_text(json.dumps({'completeness':'verified_scope','missing_parts':['head and hair omitted by scope'],'meshes':names,'fingerprints':expected,'source_geometry_unchanged':True,'saved_file_reopened':True,'geometry':analysis},ensure_ascii=False,indent=2),encoding='utf-8')
print('BODY_DECISION',decision['status'],decision['message'])
