import unittest,tempfile,hashlib,json
from pathlib import Path
from unittest.mock import patch
from extract import execute,PROFILES
from runner import sha256,write_json,prepare
class SourceGuards(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.run=Path(self.temp.name)
        (self.run/'input').mkdir();(self.run/'sword').mkdir()
        self.ini=self.run/'input/mod.ini';self.ini.write_text('source geometry fixture',encoding='utf-8')
        self.rows=[{'path':'mod.ini','size':self.ini.stat().st_size,'sha256':sha256(self.ini)}]
        digest=hashlib.sha256(json.dumps(self.rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.job={'name':'iuno','source_manifest_sha256':digest,'source_manifest':self.rows,'main_ini':str(self.ini),'sword':str(self.run/'sword')}
        write_json(self.run/'job.json',self.job)
        self.profile={'manifest':digest,'ini':'mod.ini','author':'fixture'}
    def tearDown(self):self.temp.cleanup()
    def test_changed_input_stops_before_engine_or_outputs(self):
        self.ini.write_text('tampered bytes',encoding='utf-8')
        with patch.dict(PROFILES,{'iuno':self.profile}),self.assertRaisesRegex(ValueError,'source hash'):
            execute(self.run,'iuno')
        self.assertFalse((self.run/'pipeline-result.json').exists())
    def test_incomplete_manifest_cannot_use_known_digest(self):
        self.job['source_manifest']=[];write_json(self.run/'job.json',self.job)
        with patch.dict(PROFILES,{'iuno':self.profile}),self.assertRaisesRegex(ValueError,'manifest itself'):
            execute(self.run,'iuno')
    def test_existing_output_requires_explicit_work_copy_rerun(self):
        (self.run/'models').mkdir();existing=self.run/'models/full.blend';existing.write_bytes(b'keep exact file')
        with patch.dict(PROFILES,{'iuno':self.profile}),self.assertRaisesRegex(ValueError,'already exist'):
            execute(self.run,'iuno')
        self.assertEqual(existing.read_bytes(),b'keep exact file')
    def test_external_ini_path_is_rejected(self):
        self.job['main_ini']=str(self.run/'outside.ini');write_json(self.run/'job.json',self.job)
        with patch.dict(PROFILES,{'iuno':self.profile}),self.assertRaisesRegex(ValueError,'outside'):
            execute(self.run,'iuno')
    def test_outputs_cannot_modify_source_directory(self):
        with patch('runner.resolve_paths',return_value={'work_root':str(self.run/'input/output'),'library_root':str(self.run/'library')}):
            with self.assertRaisesRegex(ValueError,'original Mod'):
                prepare('iuno',self.run/'input','WW','mod.ini')
        self.assertFalse((self.run/'input/output').exists())
if __name__=='__main__':unittest.main()
