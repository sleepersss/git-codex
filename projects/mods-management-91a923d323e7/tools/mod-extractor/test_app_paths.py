import tempfile,unittest,json
from pathlib import Path
from app_paths import resolve_paths,check_dependencies,worker_command
class PathsTests(unittest.TestCase):
    def test_explicit_chinese_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'设置.json';p.write_text(json.dumps({'work_root':str(Path(d)/'任务'),'library_root':str(Path(d)/'素材')}))
            cfg=resolve_paths(p)
            self.assertEqual(Path(cfg['work_root']).name,'任务')
            self.assertFalse(all(x['ok'] for x in check_dependencies(cfg)))
    def test_frozen_worker_dispatch(self):
        self.assertEqual(worker_command('job.json',frozen=True)[1:],['--worker-task','job.json'])
