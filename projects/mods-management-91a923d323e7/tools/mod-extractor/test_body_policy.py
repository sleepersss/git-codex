import unittest
from body_policy import evaluate_body, REQUIRED_REGIONS

class BodyPolicyTests(unittest.TestCase):
    def test_source_name_does_not_replace_current_evidence(self):
        self.assertEqual(evaluate_body('iuno', {})['status'], 'unverified')
        evidence={'regions':dict.fromkeys(REQUIRED_REGIONS,'verified'),'skin_only':True,
                  'source_manifest_verified':True,'scope':'headless_body'}
        self.assertEqual(evaluate_body('iuno',evidence)['status'],'eligible')
        evidence['regions']['left_foot']='gap'
        self.assertEqual(evaluate_body('iuno',evidence)['status'],'abandoned')
    def test_no_evidence_never_passes(self):
        self.assertEqual(evaluate_body('denia', {})['status'], 'unverified')
    def test_complete_evidence_passes(self):
        evidence={'regions': dict.fromkeys(REQUIRED_REGIONS, 'verified'), 'skin_only': True,
                  'source_manifest_verified': True, 'scope': 'headless_body'}
        self.assertEqual(evaluate_body('test', evidence)['status'], 'eligible')
        evidence['regions']['left_foot']='gap'
        self.assertEqual(evaluate_body('test', evidence)['status'], 'abandoned')
    def test_clothes_or_unknown_area_never_passes(self):
        evidence={'regions':dict.fromkeys(REQUIRED_REGIONS, 'verified'), 'skin_only':False,
                  'source_manifest_verified':True, 'scope':'headless_body'}
        self.assertEqual(evaluate_body('test', evidence)['status'], 'unverified')
    def test_old_body_output_is_rejected(self):
        import tempfile
        from pathlib import Path
        from body_policy import output_roles
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'models').mkdir();(p/'models/body.blend').write_bytes(b'old')
            with self.assertRaisesRegex(ValueError, 'body'):
                output_roles(p, {'status':'abandoned'})

