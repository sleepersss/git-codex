import bpy,sys,json
from pathlib import Path
from mathutils.bvhtree import BVHTree
from mathutils import Vector
run=Path(sys.argv[sys.argv.index('--')+1]);a=json.loads((run/'body-analysis.json').read_text(encoding='utf-8'));bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
gap=a['geometry']['gaps'][0];lo=gap['min'];hi=gap['max']
points=[tuple(o.matrix_world@v.co) for o in bpy.data.objects if o.name in a['chosen'] for v in o.data.vertices if all(lo[i]-1e-6<=v.co[i]<=hi[i]+1e-6 for i in range(3))]
rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.name in a['chosen']:continue
 tree=BVHTree.FromPolygons([tuple(o.matrix_world@v.co) for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons])
 ds=[tree.find_nearest(Vector(p))[3] for p in points]
 rows.append({'name':o.name,'max':max(ds),'mean':sum(ds)/len(ds),'draw':json.loads(o.get('SourceDraw','{}'))})
(run/'boundary-source-diagnosis.json').write_text(json.dumps(sorted(rows,key=lambda r:r['max'])[:10],ensure_ascii=False,indent=2),encoding='utf-8')
