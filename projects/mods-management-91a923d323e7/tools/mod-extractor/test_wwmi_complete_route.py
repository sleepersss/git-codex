import unittest
from wwmi_extract import uses_complete_wwmi


class WWMIRecordedFilesTests(unittest.TestCase):
    def test_body_hash_is_taken_after_later_blender_saves(self):
        import tempfile
        from pathlib import Path
        from runner import sha256
        from wwmi_extract import recorded_model_files
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);(run/'models').mkdir();body=run/'models/body.blend';full=run/'models/full.blend'
            full.write_bytes(b'full-before');body.write_bytes(b'body-before-texcoord')
            stale={'path':str(body),'sha256':sha256(body)}
            body.write_bytes(b'body-after-texcoord-and-verify')
            files=recorded_model_files(run,('full','body'))
            self.assertEqual(files['body']['sha256'],sha256(body))
            self.assertNotEqual(files['body']['sha256'],stale['sha256'])
            self.assertEqual(files['full']['sha256'],sha256(full))


class WWMICompleteRouteTests(unittest.TestCase):
    def test_auto_wwmi_uses_complete_pipeline(self):
        self.assertTrue(uses_complete_wwmi({'ini':'mod1.ini'},'WW'))
        self.assertTrue(uses_complete_wwmi({'ini':'mod.ini'},'WWMI'))

    def test_hsr_stays_on_generic_static_reader(self):
        self.assertFalse(uses_complete_wwmi({'ini':'mod.ini'},'HSR'))

    def test_reviewed_profiles_keep_dedicated_entry(self):
        self.assertFalse(uses_complete_wwmi('denia','WW'))
        self.assertFalse(uses_complete_wwmi('iuno','WWMI'))
