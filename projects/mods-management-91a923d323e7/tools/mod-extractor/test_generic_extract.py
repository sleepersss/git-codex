import unittest,tempfile
from pathlib import Path
from discovery import discover_mod
from generic_extract import plan_meshes

class MeshPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in ('points','faces','second'):(self.root/(name+'.buf')).write_bytes(b'\0'*36)
    def tearDown(self):self.tmp.cleanup()
    def ini(self,text):
        p=self.root/'other.ini';p.write_text('; WWMI\n'+text,encoding='utf-8');return p
    def resources(self):return '[ResourcePoints]\nstride=12\nfilename=points.buf\n[ResourceFaces]\nformat=DXGI_FORMAT_R32_UINT\nfilename=faces.buf\n'
    def test_custom_names_and_shared_command_binding(self):
        p=self.ini(self.resources()+'[CommandListBind]\nvb0=ResourcePoints\nib=ResourceFaces\n[TextureOverrideOther]\nrun=CommandListBind\ndrawindexed=3,0,0\n')
        self.assertTrue(discover_mod(self.root)['supported']);self.assertEqual(plan_meshes(self.root,p)[0]['bindings']['ib']['file'],'faces.buf')
    def test_multiple_index_groups_follow_own_bindings(self):
        p=self.ini(self.resources()+'[ResourceSecond]\nformat=R32_UINT\nfilename=second.buf\n[CommandListA]\nib=ResourceFaces\n[CommandListB]\nib=ResourceSecond\n[TextureOverrideA]\nvb0=ResourcePoints\nrun=CommandListA\ndrawindexed=3,0,0\n[TextureOverrideB]\nvb0=ResourcePoints\nrun=CommandListB\ndrawindexed=3,0,0\n')
        self.assertEqual([q['bindings']['ib']['file'] for q in plan_meshes(self.root,p)],['faces.buf','second.buf'])
    def test_ambiguous_binding_stops_instead_of_first_resource(self):
        p=self.ini(self.resources()+'[ResourceSecond]\nformat=R32_UINT\nfilename=second.buf\n[CommandListA]\nib=ResourceFaces\n[CommandListB]\nib=ResourceSecond\n[TextureOverrideA]\nvb0=ResourcePoints\ndrawindexed=3,0,0\n')
        with self.assertRaisesRegex(ValueError,'无法确定'):plan_meshes(self.root,p)
    def test_dynamic_draw_does_not_silently_drop(self):
        p=self.ini(self.resources()+'[TextureOverrideA]\nvb0=ResourcePoints\nib=ResourceFaces\ndrawindexed=3,0,0\ndrawindexed=$count,0,0\n')
        with self.assertRaisesRegex(ValueError,'动态'):plan_meshes(self.root,p)
    def test_cleared_index_does_not_use_stale_resource(self):
        p=self.ini(self.resources()+'[TextureOverrideA]\nvb0=ResourcePoints\nib=ResourceFaces\nib=null\ndrawindexed=3,0,0\n')
        with self.assertRaisesRegex(ValueError,'无法确定'):plan_meshes(self.root,p)
    def test_unknown_position_does_not_use_stale_resource(self):
        p=self.ini(self.resources()+'[TextureOverrideA]\nvb0=ResourcePoints\nib=ResourceFaces\nvb0=ref Unknown\ndrawindexed=3,0,0\n')
        with self.assertRaisesRegex(ValueError,'无法确定'):plan_meshes(self.root,p)
    def test_cycle_does_not_silently_drop_draws(self):
        p=self.ini(self.resources()+'[TextureOverrideA]\nvb0=ResourcePoints\nib=ResourceFaces\nrun=CommandListCycle\ndrawindexed=3,0,0\n[CommandListCycle]\nrun=CommandListCycle\n')
        with self.assertRaisesRegex(ValueError,'循环'):plan_meshes(self.root,p)
