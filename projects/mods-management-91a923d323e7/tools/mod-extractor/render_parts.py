import bpy,sys,json
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve()
job=json.loads((run/'job.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
objects=[o for o in bpy.data.objects if o.type=='MESH']
inspector=Path(__file__).resolve().parents[2]/'model-library/inspect_blend.py'
selected=[o for o in objects if job['name']=='iuno' or (o['SourceGroup']=='ib0' and o['SourceComponent']==3 and 'Body' in json.loads(o['SourceDraw'])['label'])]
for obj in selected:
    for o in objects:o.hide_render=True;o.hide_set(True)
    obj.hide_render=False;obj.hide_set(False)
    folder=run/'parts'/obj.name
    sys.argv=['blender','--',str(folder),'--previews']
    exec(compile(inspector.read_text(encoding='utf-8'),str(inspector),'exec'),{'__name__':'__main__'})
print('PART_PREVIEWS_DONE',len(selected))
