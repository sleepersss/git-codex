"""Independent body/full subset comparison: no new faces or edited source vertices."""
import bpy,numpy as np,sys,json
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve();selection=json.loads((run/'body-selection.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'));saved={}
def values(data,field,width,dtype='f4'):
 a=np.empty(len(data)*width,dtype=dtype);data.foreach_get(field,a);return a.reshape(-1,width) if width>1 else a
def capture(o):
 m=o.data;m.calc_normals_split();idx=values(m.attributes['SourceVertexIndex'].data,'value',1,'i4');loops=values(m.loops,'vertex_index',1,'i4');tri=idx[loops].reshape(-1,3)
 return {'idx':idx,'pos':values(m.vertices,'co',3),'tri':tri,'uv':{a.name:values(a.data,'uv',2) for a in m.uv_layers},
  'color':{a.name:values(a.data,'color',4) for a in m.vertex_colors},'normals':values(m.loops,'normal',3),
  'raw':{a.name:values(a.data,'value',1,'i4') for a in m.attributes if a.data_type=='INT' and a.domain=='POINT'},
  'shapes':{a.name:values(a.data,'co',3) for a in m.shape_keys.key_blocks} if m.shape_keys else {},
  'weights':[sorted((o.vertex_groups[g.group].name,g.weight) for g in v.groups) for v in m.vertices]}
for row in selection['meshes']:
 name=row['name'] if isinstance(row,dict) else row;saved[name]=capture(bpy.data.objects[name])
bpy.ops.wm.open_mainfile(filepath=str(run/'models/body.blend'));checks=[]
for o in [o for o in bpy.data.objects if o.type=='MESH']:
 before=saved[o.name];after=capture(o);lookup={int(v):i for i,v in enumerate(before['idx'])};mapping=np.array([lookup[int(v)] for v in after['idx']])
 assert np.array_equal(after['pos'],before['pos'][mapping]),o.name+' positions'
 for name,data in before['raw'].items():assert np.array_equal(after['raw'][name],data[mapping]),o.name+' raw '+name
 assert set(after['shapes'])==set(before['shapes'])
 for name,data in before['shapes'].items():assert np.array_equal(after['shapes'][name],data[mapping]),o.name+' shape '+name
 assert after['weights']==[before['weights'][i] for i in mapping],o.name+' weights'
 def canonical(t):return min(tuple(t),tuple(t[1:])+tuple(t[:1]),tuple(t[2:])+tuple(t[:2]))
 triangles={canonical(t):i for i,t in enumerate(before['tri'])};loopmap=[]
 for t in after['tri']:
  key=canonical(t);assert key in triangles,o.name+' fabricated triangle'
  i=triangles[key];old=list(before['tri'][i]);loopmap.extend(i*3+old.index(v) for v in t)
 for name,data in before['uv'].items():assert np.array_equal(after['uv'][name],data[loopmap]),o.name+' UV '+name
 for name,data in before['color'].items():assert np.array_equal(after['color'][name],data[loopmap]),o.name+' color '+name
 normal_error=float(np.max(np.abs(after['normals']-before['normals'][loopmap])))
 a=after['normals'].astype('f8');b=before['normals'][loopmap].astype('f8')
 angles=np.degrees(np.arctan2(np.linalg.norm(np.cross(a,b),axis=1),np.sum(a*b,axis=1)))
 max_angle=float(np.max(angles))
 assert max_angle<.1,o.name+' split normal angle difference '+str(max_angle)
 checks.append({'object':o.name,'vertices':len(after['idx']),'triangles':len(after['tri']),'source_position_exact':True,'source_faces_only':True,'raw_attributes_exact':True,'uv_exact':True,'color_exact':True,'weights_exact':True,'shape_targets_exact':True,'split_normals_max_error':normal_error,'split_normals_max_angle_degrees':max_angle,'normal_quantization_limit_degrees':.1})
assert checks and set(saved)=={r['object'] for r in checks}
(run/'body-source-verification.json').write_text(json.dumps({'status':'passed','checks':checks,'scope':'source body subset; no filled gaps or reconstructed limbs'},ensure_ascii=False,indent=2),encoding='utf-8')
