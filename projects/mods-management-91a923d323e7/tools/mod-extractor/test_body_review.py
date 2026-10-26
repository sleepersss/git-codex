import unittest,tempfile
from pathlib import Path
from runner import write_json
from body_review import write_body_review


class BodyReviewTests(unittest.TestCase):
    def test_source_text_is_escaped_and_alternatives_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)
            write_json(run/'body-candidates.json',{'status':'ambiguous','states_evaluated':2,
                'selected':[],'alternatives':[{'names':['<script>alert(1)</script>'],
                    'controls':{'v':1},'regions':['body']}],
                'parts':[{'name':'<img src=x onerror=alert(2)>','label':'Body','conditions':[]}],
                'excluded':[],'unresolved':[]})
            write_json(run/'body-decision.json',{'message':'多个身体版本，待核对。'})
            p=write_body_review(run)
            html=p.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;',html)
            self.assertNotIn('<script>',html)
            self.assertNotIn('<img src=x',html)
            self.assertIn('待核对',html)
            self.assertIn('v',html)

    def test_failed_body_analysis_still_has_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);write_json(run/'body-decision.json',{'message':'检查未完成'})
            self.assertTrue(write_body_review(run).is_file())
