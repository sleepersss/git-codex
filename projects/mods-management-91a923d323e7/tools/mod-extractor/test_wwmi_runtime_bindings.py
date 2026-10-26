"""Runtime-buffer binding regression reduced from the user's Suoming failure."""
import unittest,tempfile,struct
from pathlib import Path
from generic_extract import plan_meshes


class WWMIRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        (self.root/'base.buf').write_bytes(struct.pack('<9f',0,0,0,1,0,0,0,1,0))
        (self.root/'other.buf').write_bytes(struct.pack('<9f',0,0,0,2,0,0,0,2,0))
        (self.root/'index.buf').write_bytes(struct.pack('<3I',0,1,2))

    def text(self):
        return '''; WWMI BETA-8 INI
[ResourceBasePosition]
type=Buffer
format=R32G32B32_FLOAT
stride=12
filename=base.buf
[ResourceOtherPosition]
type=Buffer
format=R32G32B32_FLOAT
stride=12
filename=other.buf
[ResourceIndexBuffer]
format=R32_UINT
filename=index.buf
[ResourceShapeKeyedPosition]
[ResourcePositionRW]
type=RWBuffer
format=R32_FLOAT
stride=12
[CommandListApplyShapeKeys]
cs-t6=ResourceBasePosition
cs-u6=ResourcePositionRW
run=CustomShader\WWMIv1\ShapeKeyApplier
ResourceShapeKeyedPosition=copy ResourcePositionRW
[CommandListOverrideSharedResources]
ib=ResourceIndexBuffer
vb0=ResourceShapeKeyedPosition
[TextureOverrideComponent0]
run=CommandListOverrideSharedResources
; Draw Component 0.001
drawindexed=3,0,0
'''

    def plan(self,text):
        p=self.root/'mod.ini';p.write_text(text,encoding='utf-8')
        return plan_meshes(self.root,p)

    def test_known_wwmi_producer_resolves_its_exact_source_base(self):
        plans=self.plan(self.text())
        self.assertEqual(len(plans),1)
        self.assertEqual(plans[0]['bindings']['vb0']['file'],'base.buf')
        self.assertEqual(plans[0]['runtime_position']['status'],'source_base_only')
        self.assertEqual(plans[0]['runtime_position']['runtime_resource'],'resourceshapekeyedposition')

    def test_unknown_shader_never_uses_a_convenient_base(self):
        with self.assertRaisesRegex(ValueError,'绑定'):
            self.plan(self.text().replace('WWMIv1\\ShapeKeyApplier','Other\\ShapeKeyApplier'))

    def test_missing_copy_cannot_establish_runtime_alias(self):
        with self.assertRaisesRegex(ValueError,'绑定'):
            self.plan(self.text().replace('ResourceShapeKeyedPosition=copy ResourcePositionRW',''))

    def test_conditional_producer_is_not_assumed_to_run(self):
        text=self.text().replace('cs-t6=ResourceBasePosition','if $unknown\ncs-t6=ResourceBasePosition').replace(
            'ResourceShapeKeyedPosition=copy ResourcePositionRW','ResourceShapeKeyedPosition=copy ResourcePositionRW\nendif')
        with self.assertRaisesRegex(ValueError,'绑定'):self.plan(text)

    def test_competing_producers_cannot_silently_select_first(self):
        second='\n[CommandListOtherProducer]\ncs-t6=ResourceOtherPosition\ncs-u6=ResourcePositionRW\nrun=CustomShader\\WWMIv1\\ShapeKeyApplier\nResourceShapeKeyedPosition=copy ResourcePositionRW\n'
        with self.assertRaisesRegex(ValueError,'绑定'):self.plan(self.text()+second)

    def test_runtime_provenance_is_not_lost_when_base_draw_is_identical(self):
        text=self.text().replace('run=CommandListOverrideSharedResources\n; Draw Component 0.001',
            'ib=ResourceIndexBuffer\nvb0=ResourceBasePosition\ndrawindexed=3,0,0\nrun=CommandListOverrideSharedResources')
        plans=self.plan(text)
        self.assertTrue(any(p.get('runtime_position') for p in plans))
        self.assertTrue(any(not p.get('runtime_position') for p in plans))

    def test_output_overwrite_invalidates_lineage(self):
        text=self.text().replace('ResourceShapeKeyedPosition=copy ResourcePositionRW',
            'ResourcePositionRW=copy ResourceOtherPosition\nResourceShapeKeyedPosition=copy ResourcePositionRW')
        with self.assertRaisesRegex(ValueError,'绑定'):self.plan(text)

    def test_invalid_second_producer_cannot_reuse_old_lineage(self):
        text=self.text().replace('ResourceShapeKeyedPosition=copy ResourcePositionRW',
            'cs-t6=ResourceUnknown\nrun=CustomShader\\WWMIv1\\ShapeKeyApplier\nResourceShapeKeyedPosition=copy ResourcePositionRW')
        with self.assertRaisesRegex(ValueError,'绑定'):self.plan(text)

    def test_producer_in_another_section_cannot_overwrite_output_unnoticed(self):
        second='\n[CommandListOtherProducer]\ncs-t6=ResourceOtherPosition\ncs-u6=ResourcePositionRW\nrun=CustomShader\\WWMIv1\\ShapeKeyApplier\n'
        with self.assertRaisesRegex(ValueError,'绑定'):self.plan(self.text()+second)

