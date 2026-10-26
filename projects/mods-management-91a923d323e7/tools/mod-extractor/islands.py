import bpy,sys,json,collections
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o['SourceComponent']==3)
mesh=obj.data;parent=list(range(len(mesh.vertices)))
def root(x):
    while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
    return x
for e in mesh.edges:parent[root(e.vertices[1])]=root(e.vertices[0])
groups=collections.defaultdict(list)
for v in mesh.vertices:groups[root(v.index)].append(v.index)
parts=[]
for i,vertices in enumerate(sorted(groups.values(),key=lambda x:-len(x))):
    points=[mesh.vertices[v].co for v in vertices]
    parts.append({'id':i,'vertices':vertices,'count':len(vertices),'min':[min(p[a] for p in points) for a in range(3)],'max':[max(p[a] for p in points) for a in range(3)]})
(run/'islands.json').write_text(json.dumps(parts),encoding='utf-8')
print(json.dumps([{k:v for k,v in p.items() if k!='vertices'} for p in parts[:35]],indent=2))
