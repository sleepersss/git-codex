import unittest,tempfile,json,struct,subprocess
from pathlib import Path
from app_paths import resolve_paths

class BlenderReaderTests(unittest.TestCase):
    def check(self,mismatch=False):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);root=run/'input';root.mkdir()
            (root/'position.buf').write_bytes(struct.pack('<9f',0,0,0,1,0,0,0,1,0))
            (root/'index.buf').write_bytes(struct.pack('<3I',0,1,2))
            (root/'packed.buf').write_bytes(bytes(range(10 if mismatch else 15)))
            b={'vb0':{'file':'position.buf','stride':'12','name':'ResourcePosition'},'ib':{'file':'index.buf','format':'R32_UINT','name':'ResourceIndex'},
                'vb1':{'file':'packed.buf','stride':'5','name':'ResourcePacked'}}
            (run/'mesh-plan.json').write_text(json.dumps([{'bindings':b,'section':'other','count':3,'start':0,'base':0}]))
            script=Path(__file__).with_name('import_generic.py')
            p=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script),'--',str(run)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            if mismatch:
                self.assertNotEqual(p.returncode,0);self.assertFalse((run/'generic-verification.json').exists())
            else:
                self.assertEqual(p.returncode,0,p.stdout.decode(errors='replace'))
                report=json.loads((run/'generic-verification.json').read_text(encoding='utf-8'))
                self.assertEqual(report['status'],'passed');self.assertTrue(report['fingerprints'])
    def test_trailing_vertex_bytes_save_and_reopen(self):self.check()
    def test_attribute_count_mismatch_is_not_success(self):self.check(True)
