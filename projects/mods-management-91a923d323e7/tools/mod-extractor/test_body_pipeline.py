import unittest,tempfile,subprocess
from pathlib import Path
from unittest.mock import patch
from runner import write_json
from body_pipeline import extract_source_body

class BodyPipelineTests(unittest.TestCase):
    def test_report_failure_does_not_discard_full_or_body_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('body_pipeline._extract_source_body',return_value={'body_status':'available'}),\
                 patch('body_review.write_body_review',side_effect=OSError('report unavailable')):
                result=extract_source_body(Path(tmp))
            self.assertEqual(result['body_status'],'available')
            self.assertEqual(result['body_report_status'],'unavailable')
    def test_analysis_failure_quarantines_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);write_json(run/'job.json',{'blender':'blender'})
            (run/'models').mkdir();(run/'models/body.blend').write_bytes(b'candidate')
            with patch('body_pipeline.subprocess.run',side_effect=ValueError('bad selection')):
                result=extract_source_body(run)
            self.assertEqual(result['body_status'],'unverified')
            self.assertFalse((run/'models/body.blend').exists())
            self.assertEqual(next((run/'rejected').glob('*.blend')).read_bytes(),b'candidate')
            self.assertTrue((run/'body-review.html').is_file())
    def test_body_failure_preserves_full_model_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);write_json(run/'job.json',{'blender':'blender'})
            with patch('body_pipeline.subprocess.run',return_value=type('Result',(),{'returncode':1})()):
                result=extract_source_body(run)
            self.assertEqual(result['body_status'],'unverified')
            self.assertNotIn('body_file',result)
            self.assertTrue((run/'body-decision.json').exists())
    def test_timeout_does_not_invalidate_full_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);write_json(run/'job.json',{'blender':'blender'})
            with patch('body_pipeline.subprocess.run',side_effect=subprocess.TimeoutExpired('blender',300)):
                self.assertEqual(extract_source_body(run)['body_status'],'unverified')
