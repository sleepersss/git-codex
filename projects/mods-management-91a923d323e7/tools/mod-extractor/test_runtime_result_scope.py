import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from generic_extract import execute_generic
from runner import write_json


class RuntimeResultScopeTests(unittest.TestCase):
    def test_source_base_only_result_is_partial_and_does_not_generate_body(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'input').mkdir();(r/'models').mkdir();(r/'models/full.blend').write_bytes(b'fixture')
            ini=r/'input/mod.ini';ini.write_text('[TextureOverrideA]\ndrawindexed=3,0,0\n',encoding='utf-8')
            write_json(r/'job.json',{'source_manifest':[],'main_ini':str(ini),'blender':'blender',
                'game':'WW','library_game':'WW','character':'test'})
            plan={'section':'TextureOverrideA','count':3,'start':0,'base':0,
                'runtime_position':{'status':'source_base_only','runtime_resource':'ResourceRuntime'}}
            def imported(*args,**kwargs):
                write_json(r/'generic-verification.json',{'status':'passed','fingerprints':{},'mesh_count':1})
                return type('Result',(),{'returncode':0})()
            with patch('generic_extract.plan_meshes',return_value=[plan]),\
                 patch('generic_extract.subprocess.run',side_effect=imported),\
                 patch('body_pipeline.extract_source_body',return_value={'body_status':'unverified'}) as body:
                result=execute_generic(r)
            body.assert_not_called()
            self.assertEqual(result['full_status'],'partial')
            self.assertEqual(result['body_status'],'unverified')
            self.assertEqual(result['runtime_geometry_status'],'unverified')
            self.assertEqual(result['source_draw_coverage']['covered'],1)
            self.assertNotIn('body',result['files'])

