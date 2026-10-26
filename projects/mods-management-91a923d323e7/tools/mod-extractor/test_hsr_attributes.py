import unittest,tempfile,json,struct,subprocess
from pathlib import Path
from app_paths import resolve_paths

class HSRAttributeTests(unittest.TestCase):
    def test_color_and_half_uv_are_decoded_as_separate_stream_fields(self):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);root=run/'input';root.mkdir()
            (root/'position.buf').write_bytes(struct.pack('<9f',0,0,0,1,0,0,0,1,0))
            (root/'index.buf').write_bytes(struct.pack('<3I',0,1,2))
            (root/'uv.buf').write_bytes(b''.join(bytes([255,128,64,255])+struct.pack('<2e',u,v) for u,v in [(0,0),(1,0),(0,1)]))
            plan={'section':'HSR','count':3,'start':0,'base':0,'game':'HSR','bindings':{
                'vb0':{'name':'ResourcePosition','file':'position.buf','stride':'12'},
                'vb1':{'name':'ResourceTexcoord','file':'uv.buf','stride':'8'},
                'ib':{'name':'ResourceIndex','file':'index.buf','format':'R32_UINT'}}}
            (run/'mesh-plan.json').write_text(json.dumps([plan]))
            check=run/'check.py';check.write_text("import bpy,json,sys\nfrom pathlib import Path\nr=Path(sys.argv[sys.argv.index('--')+1]);o=next(o for o in bpy.data.objects if o.type=='MESH');m=o.data\n(r/'decoded.json').write_text(json.dumps({'uv':[[list(x.uv) for x in l.data] for l in m.uv_layers], 'colors':len(m.vertex_colors), 'up':list(o.matrix_world @ m.vertices[2].co)}))\n")
            p=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(Path(__file__).with_name('import_generic.py')),'--python',str(check),'--',str(run)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            self.assertEqual(p.returncode,0,p.stdout.decode(errors='replace'))
            decoded=json.loads((run/'decoded.json').read_text())
            self.assertEqual(decoded['uv'],[[[0,1],[1,1],[0,0]]])
            self.assertEqual(decoded['colors'],1)
            self.assertAlmostEqual(decoded['up'][2],1)

if __name__=='__main__':unittest.main()
