import tempfile,unittest,struct
from pathlib import Path
from wwmi_shapekeys import load_shapekeys,named_channels


class WWMIShapeKeyTests(unittest.TestCase):
    def test_named_custom_channels_come_from_ini(self):
        text='[CommandListSetBoobsSize]\n$\\WWMIv1\\shapekey_id = 161\n$\\WWMIv1\\shapekey_value = $BoobsSize\n'
        self.assertEqual(named_channels(text),{161:'BoobsSize'})

    def test_128_channel_offset_table_is_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            meshes=Path(tmp)
            offsets=[0]*128;offsets[0]=0;offsets[1]=1;offsets[2]=2
            (meshes/'ShapeKeyOffset.buf').write_bytes(struct.pack('<'+'I'*128,*offsets))
            (meshes/'ShapeKeyVertexId.buf').write_bytes(struct.pack('<2I',7,9))
            row=struct.pack('<6f',0.5,0,0,0,0,0)+struct.pack('<6f',0,1.5,0,0,0,0)
            (meshes/'ShapeKeyVertexOffset.buf').write_bytes(row)
            result=load_shapekeys(meshes)
            self.assertEqual(result['status'],'decoded')
            self.assertEqual(result['layout'],'wwmi_128_offset')
            self.assertEqual(result['channels'][0]['vertices'][7],[0.5,0.0,0.0])
            self.assertEqual(result['channels'][1]['vertices'][9],[0.0,1.5,0.0])
            self.assertNotIn(2,result['channels'])

    def test_half_float_rows_and_second_batch_are_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            meshes=Path(tmp)
            offsets=[1]*256;offsets[0]=0;offsets[128]=0
            (meshes/'ShapeKeyOffset.buf').write_bytes(struct.pack('<'+'I'*256,*offsets))
            (meshes/'ShapeKeyVertexId.buf').write_bytes(struct.pack('<2I',7,11))
            row=struct.pack('<6e',0.5,0,0,0,0,0)+struct.pack('<6e',0,1.5,0,0,0,0)
            (meshes/'ShapeKeyVertexOffset.buf').write_bytes(row)
            result=load_shapekeys(meshes)
            self.assertEqual(result['status'],'decoded')
            self.assertEqual(result['batches'],2)
            self.assertIn('f16',result['layout'])
            self.assertAlmostEqual(result['channels'][0]['vertices'][7][0],0.5,places=2)
            self.assertAlmostEqual(result['channels'][0]['vertices'][11][1],1.5,places=2)

    def test_missing_buffers_are_absent_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=load_shapekeys(Path(tmp))
            self.assertEqual(result['status'],'absent')
            self.assertFalse(result['channels'])
