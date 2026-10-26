"""Non-finite half data must remain raw, never silently accepted as valid UV."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from app_paths import resolve_paths


class AmbiguousTexcoordTests(unittest.TestCase):
    def test_only_affected_mesh_lane_is_parked_with_original_bytes(self):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);script=run/'fixture.py';worker=Path(__file__).with_name('retain_texcoord.py')
            verifier=Path(__file__).with_name('verify_wwmi.py')
            code='''import bpy,numpy as np,json,sys,runpy
from pathlib import Path
run=Path(RUN);(run/'models').mkdir();(run/'input/Meshes').mkdir(parents=True)
tex=np.tile(np.array([.1,.2,.3,.4,.5,.6,.7,.8],dtype='<f2'),(6,1));tex[0,2]=np.nan
(run/'input/Meshes/TexCoord.buf').write_bytes(tex.tobytes())
(run/'input/mod.ini').write_text('; fixture')
np.tile(np.array([(0,0,0),(1,0,0),(0,1,0)],dtype='<f4'),(2,1)).tofile(run/'input/Meshes/Position.buf')
(run/'input/Meshes/Blend.buf').write_bytes(bytes(6*16))
(run/'input/Meshes/Color.buf').write_bytes(bytes(6*4))
np.arange(6,dtype='<u4').tofile(run/'input/Meshes/Index.buf')
(run/'fixture.fmt').write_text('stride: 12')
(run/'fixture.vb').write_bytes(bytes(3*12))
np.arange(3,dtype='<u4').tofile(run/'fixture.ib')
(run/'job.json').write_text(json.dumps({'name':'auto','main_ini':str(run/'input/mod.ini')}))
(run/'body-decision.json').write_text(json.dumps({'status':'unverified'}))
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for name,start in [('bad',0),('good',3)]:
 mesh=bpy.data.meshes.new(name);mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
 obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj['SourceGroup']=''
 obj['SourceDraw']=json.dumps({'start':start,'count':3});obj['SourceFmt']=str(run/'fixture.fmt');obj['SourceStride']=12
 for lane in range(4):mesh.attributes.new(name='SourceBlendRaw'+str(lane),type='INT',domain='POINT')
 colors=mesh.vertex_colors.new(name='COLOR')
 for value in colors.data:value.color=(0,0,0,0)
 attr=mesh.attributes.new(name='SourceVertexIndex',type='INT',domain='POINT')
 for i in range(3):attr.data[i].value=start+i
 for lane in range(4):
  layer=mesh.uv_layers.new(name='TEXCOORD'+(str(lane) if lane else '')+'.xy')
  for i in range(3):
   value=tex[start+i,2*lane:2*lane+2].astype('f4');value[1]=1-value[1]
   layer.data[i].uv=np.nan_to_num(value)
bpy.ops.wm.save_as_mainfile(filepath=str(run/'models/full.blend'))
sys.argv=['retain','--',str(run)];runpy.run_path(WORKER,run_name='__main__')
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
bad=bpy.data.objects['bad'];good=bpy.data.objects['good']
assert bad.data.uv_layers.get('TEXCOORD1.xy') is None,'invalid half values still labelled UV'
assert len(good.data.uv_layers)==4,'unaffected mesh UV was removed'
assert len(bad.data.vertices)==3 and len(bad.data.polygons)==1
assert 'TEXCOORD1.xy' not in json.loads(bad['UVSourceLaneMap'])
assert json.loads(bad['AmbiguousTexcoordLanes'])[0]['raw_attribute']=='SourceTexcoordRaw1'
for obj,start in [(bad,0),(good,3)]:
 for lane in range(4):
  actual=np.array([v.value for v in obj.data.attributes['SourceTexcoordRaw'+str(lane)].data],dtype='<i4')
  assert actual.tobytes()==tex[start:start+3].copy().view('u1').reshape(-1,16)[:,4*lane:4*lane+4].copy().tobytes()
assert (run/'input/Meshes/TexCoord.buf').read_bytes()==tex.tobytes()
sys.argv=['verify','--',str(run)];runpy.run_path(VERIFIER,run_name='__main__')
assert json.loads((run/'data-preservation-verification.json').read_text())['status']=='passed'
bad=bpy.data.objects['bad'];bad.data.attributes.remove(bad.data.attributes['SourceTexcoordRaw1'])
bpy.ops.wm.save_as_mainfile(filepath=str(run/'models/full.blend'))
try:runpy.run_path(VERIFIER,run_name='__main__')
except AssertionError as exc:assert 'missing SourceTexcoordRaw1' in str(exc),str(exc)
else:raise AssertionError('missing raw bytes incorrectly passed verification')
bpy.ops.wm.open_mainfile(filepath=str(run/'models/full.blend'))
bad=bpy.data.objects['bad'];raw=bad.data.attributes.new(name='SourceTexcoordRaw1',type='INT',domain='POINT')
values=tex[:3].copy().view('u1').reshape(-1,16)[:,4:8].copy().view('<i4').ravel()
for i,value in enumerate(values):raw.data[i].value=int(value)
good=bpy.data.objects['good'];good['UVSourceLaneMap']=json.dumps({'TEXCOORD.xy':0})
bpy.ops.wm.save_as_mainfile(filepath=str(run/'models/full.blend'))
try:runpy.run_path(VERIFIER,run_name='__main__')
except AssertionError as exc:assert 'source UV lane map' in str(exc),str(exc)
else:raise AssertionError('skipped valid UV incorrectly passed verification')
'''.replace('RUN',repr(str(run))).replace('WORKER',repr(str(worker))).replace('VERIFIER',repr(str(verifier)))
            script.write_text(code,encoding='utf-8')
            p=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec',
                '--python-exit-code','1','--python',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout.decode('utf-8',errors='replace'))


if __name__=='__main__':unittest.main()
