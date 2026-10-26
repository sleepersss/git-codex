"""Manual body sessions never publish an unchanged or unsaved working file."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import manual_body
from runner import write_json,sha256,read_json


class ManualBodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.run=Path(self.tmp.name)
        (self.run/'models').mkdir();self.full=self.run/'models/full.blend';self.full.write_bytes(b'BLENDER-original')
        write_json(self.run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'unverified',
            'body_reason':{},'files':{'full':{'path':str(self.full),'sha256':sha256(self.full)}}})
        write_json(self.run/'job.json',{})
        self.original=self.full.read_bytes()
    def tearDown(self):self.tmp.cleanup()
    def test_unsaved_exit_does_not_run_verifier_or_create_body(self):
        session=manual_body.prepare_session(self.run)
        with patch('manual_body.verify_session') as verify:
            result=manual_body.finish_session(session,0)
        self.assertEqual(result['status'],'unchanged');verify.assert_not_called()
        self.assertFalse((self.run/'models/body.blend').exists());self.assertEqual(self.full.read_bytes(),self.original)
    def test_same_bytes_even_with_save_witness_do_not_create_body(self):
        session=manual_body.prepare_session(self.run);d=read_json(session)
        write_json(session.parent/'saved.json',{'path':d['working'],'sha256':sha256(Path(d['working']))})
        self.assertEqual(manual_body.finish_session(session,0)['status'],'unchanged')
        self.assertFalse((self.run/'models/body.blend').exists())
    def test_crash_after_save_does_not_publish(self):
        session=manual_body.prepare_session(self.run);d=read_json(session);working=Path(d['working']);working.write_bytes(b'BLENDER-edited')
        write_json(session.parent/'saved.json',{'path':str(working),'sha256':sha256(working)})
        with patch('manual_body.verify_session') as verify:
            result=manual_body.finish_session(session,1)
        self.assertEqual(result['status'],'failed');verify.assert_not_called()
        self.assertFalse((self.run/'models/body.blend').exists())
    def test_unsaved_session_preserves_existing_body_and_report(self):
        body=self.run/'models/body.blend';body.write_bytes(b'previous body')
        before=(self.run/'pipeline-result.json').read_bytes()
        manual_body.finish_session(manual_body.prepare_session(self.run),0)
        self.assertEqual(body.read_bytes(),b'previous body')
        self.assertEqual((self.run/'pipeline-result.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
