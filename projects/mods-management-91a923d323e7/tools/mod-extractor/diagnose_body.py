import bpy,sys,json,collections,numpy as np
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]);bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'));rows=[]
for obj in bpy.data.objects:
 if obj.type!='MESH':continue
 m=obj.data;p=np.empty(len(m.vertices)*3,dtype='f4');m.vertices.foreach_get('co',p);p=p.reshape(-1,3)
 edges=collections.Counter(tuple(sorted(e)) for f in m.polygons for e in zip(f.vertices,list(f.vertices)[1:]+list(f.vertices)[:1]))
 boundary=[e for e,n in edges.items() if n==1];ids=set(v for e in boundary for v in e)
 d=json.loads(obj.get('SourceDraw','{}'))
 rows.append({'object':obj.name,'draw':d,'vertices':len(p),'faces':len(m.polygons),'min':p.min(axis=0).tolist(),'max':p.max(axis=0).tolist(),'boundary_edges':len(boundary),'boundary_min':p[list(ids)].min(axis=0).tolist() if ids else None,'boundary_max':p[list(ids)].max(axis=0).tolist() if ids else None})
(run/'body-diagnostics.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
