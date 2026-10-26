import unittest,tempfile,subprocess,struct,json
from pathlib import Path
from app_paths import resolve_paths


class WWMIWeightTests(unittest.TestCase):
    def test_eight_bone_indices_followed_by_eight_weights(self):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);p=r/'input';p.mkdir()
            (p/'position.buf').write_bytes(struct.pack('<9f',0,0,0,1,0,0,0,1,0))
            (p/'index.buf').write_bytes(struct.pack('<3I',0,1,2))
            (p/'blend.buf').write_bytes(bytes([1,2,3,4,5,6,7,8,32,32,32,32,32,32,32,31])*3)
            plan={'section':'WWMI','count':3,'start':0,'base':0,'game':'WW','bindings':{
                'vb0':{'name':'ResourcePosition','file':'position.buf','stride':'12'},
                'vb4':{'name':'ResourceBlendBuffer','file':'blend.buf','stride':'16'},
                'ib':{'name':'ResourceIndex','file':'index.buf','format':'R32_UINT'}}}
            (r/'mesh-plan.json').write_text(json.dumps([plan]),encoding='utf-8')
            check=r/'check.py';check.write_text("import bpy,json\nfrom pathlib import Path\no=next(o for o in bpy.data.objects if o.type=='MESH')\nPath("+repr(str(r/'weights.json'))+").write_text(json.dumps({o.vertex_groups[g.group].name:g.weight for g in o.data.vertices[0].groups}))",encoding='utf-8')
            script=Path(__file__).with_name('import_generic.py')
            result=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script),'--python',str(check),'--',str(r)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace'))
            weights=json.loads((r/'weights.json').read_text(encoding='utf-8'))
            self.assertEqual(set(weights),{str(i) for i in range(1,9)})
            self.assertAlmostEqual(weights['8'],31/255,places=6)
            self.assertAlmostEqual(sum(weights.values()),1,places=6)
