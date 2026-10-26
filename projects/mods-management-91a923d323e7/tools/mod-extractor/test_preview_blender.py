import unittest,tempfile,subprocess,json
from pathlib import Path
from app_paths import resolve_paths,resource_root

class PreviewScopeTests(unittest.TestCase):
    def test_preview_only_omits_hidden_mesh_statistics(self):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);blend=root/'fixture.blend';script=root/'create.py'
            script.write_text('import bpy\nbpy.ops.object.select_all(action="SELECT")\nbpy.ops.object.delete(use_global=False)\nbpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name="visible"\nbpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name="hidden"\nbpy.context.object.hide_render=True\nbpy.context.object.hide_set(True)\nbpy.ops.wm.save_as_mainfile(filepath='+repr(str(blend))+')\n',encoding='utf-8')
            common=[str(blender),'--background','--factory-startup','--disable-autoexec']
            subprocess.run(common+['--python-exit-code','1','--python',str(script)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=60)
            inspector=resource_root()/'model-library/inspect_blend.py';out=root/'previews'
            subprocess.run(common+[str(blend),'--python-exit-code','1','--python',str(inspector),'--',str(out),'--previews','--preview-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=60)
            report=json.loads((out/'inspection.json').read_text(encoding='utf-8'))
            self.assertEqual(report['mesh_count'],1)
            self.assertEqual(report['scene_mesh_count'],2)
            self.assertEqual(report['inspection_scope'],'visible_meshes_only')
            self.assertEqual({r['name'] for r in report['objects']},{'visible'})
            for view in ('front','side','back','three_quarter'):self.assertTrue((out/(view+'.png')).is_file())

if __name__=='__main__':unittest.main()
