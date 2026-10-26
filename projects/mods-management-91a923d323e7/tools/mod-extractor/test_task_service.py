import unittest,tempfile,time,sys
from pathlib import Path
from unittest.mock import patch
from task_service import TaskService
class TaskTests(unittest.TestCase):
    def test_structured_event_and_nonzero_failure(self):
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'fake.py';script.write_text('import json,sys\nprint(json.dumps({"kind":"event","stage":"verify","message":"test stage"}),flush=True)\nsys.exit(2)')
            service=TaskService()
            with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
                task=service.start('iuno',Path(d),{'work_root':d})
                service.thread.join(10)
            events=service.drain();self.assertTrue(any(e['stage']=='verify' for e in events))
            self.assertEqual(events[-1]['status'],'failed');self.assertEqual(events[-1]['task_id'],task)
    def test_cancel_stops_owned_process(self):
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'fake.py';script.write_text('import time\ntime.sleep(120)')
            service=TaskService()
            with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
                task=service.start('iuno',Path(d),{'work_root':d})
                deadline=time.time()+5
                while service.process is None and time.time()<deadline:time.sleep(.02)
                service.cancel(task);service.thread.join(10)
            self.assertFalse(service.thread.is_alive());self.assertEqual(service.drain()[-1]['status'],'cancelled')
    def test_cancel_marks_persisted_result_ineligible(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            result=Path(d)/'pipeline-result.json';result.write_text(json.dumps({'status':'passed'}))
            script=Path(d)/'fake.py'
            script.write_text('import time,json\nprint(json.dumps({"kind":"event","stage":"prepare","artifacts":{"run":'+repr(d)+'}}),flush=True)\ntime.sleep(120)')
            service=TaskService()
            with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
                task=service.start('iuno',Path(d),{'work_root':d})
                deadline=time.time()+5
                while not getattr(service,'run',None) and time.time()<deadline:time.sleep(.02)
                service.cancel(task);service.thread.join(10)
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['status'],'cancelled')
