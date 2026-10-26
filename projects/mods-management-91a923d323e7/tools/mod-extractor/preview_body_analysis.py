import bpy,sys,json,runpy
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve();bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
names=json.loads((run/'body-analysis.json').read_text(encoding='utf-8'))['chosen']
analysis=json.loads((run/'body-analysis.json').read_text(encoding='utf-8'))['geometry']
if analysis.get('up_axis')==1:
 from mathutils import Matrix
 import math
 rotation=Matrix.Rotation(math.pi/2,4,'X')
 for obj in bpy.data.objects:
  if obj.type=='MESH':obj.matrix_world=rotation @ obj.matrix_world
 for gap in analysis.get('gaps',[]):
  center=tuple((a+b)/2 for a,b in zip(gap['min'],gap['max']))
  from mathutils import Vector
  bpy.ops.mesh.primitive_uv_sphere_add(radius=.012,location=rotation @ Vector(center));marker=bpy.context.object;names.append(marker.name)
  mat=bpy.data.materials.new('Gap marker');mat.diffuse_color=(1,0,0,1);marker.data.materials.append(mat)
for obj in bpy.data.objects:
 if obj.type=='MESH':obj.hide_set(obj.name not in names);obj.hide_render=obj.name not in names
inspector=Path(__file__).resolve().parents[2]/'model-library/inspect_blend.py'
sys.argv=[str(inspector),'--',str(run/'body-analysis-previews'),'--previews'];runpy.run_path(str(inspector),run_name='__main__')
