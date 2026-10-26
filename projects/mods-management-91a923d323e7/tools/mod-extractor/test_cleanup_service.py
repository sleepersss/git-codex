import hashlib,json,tempfile,unittest
from pathlib import Path
from runner import write_json,inventory,sha256

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.work=self.root/'work';self.work.mkdir()
        self.run=self.work/'mod-extraction-test-20261011-12345678';self.run.mkdir()
        self.lib=self.root/'library';self.payload=self.lib/'sources/WW/SRC-WW-000001/payload';self.payload.mkdir(parents=True)
        (self.payload/'mod.ini').write_text('[Constants]\n$x=0\n')
        manifest,digest=inventory(self.payload)
        write_json(self.payload.parent/'metadata.json',{'id':'SRC-WW-000001','game':'WW','payload':'sources/WW/SRC-WW-000001/payload','manifest':manifest,'manifest_sha256':digest,'backup_verified':True})
        (self.run/'input').mkdir();(self.run/'input/mod.ini').write_text('[Constants]\n$x=0\n')
        (self.run/'sword').mkdir();(self.run/'sword/runtime.bin').write_bytes(b'runtime')
        (self.run/'models').mkdir();(self.run/'models/full.blend').write_bytes(b'keep model')
        (self.run/'task.log').write_text('keep log');(self.run/'unknown.bin').write_bytes(b'keep unknown')
        self.job={'name':'test','source':str(self.root/'original'),'library_root':str(self.lib),'library_game':'WW','source_id':'SRC-WW-000001','source_manifest':manifest,'source_manifest_sha256':digest,'main_ini':str(self.run/'input/mod.ini')}
        write_json(self.run/'job.json',self.job)
        self.result={'status':'passed','files':{'full':{'path':str(self.run/'models/full.blend'),'sha256':sha256(self.run/'models/full.blend')}}}
        write_json(self.run/'pipeline-result.json',self.result)
    def tearDown(self):self.temp.cleanup()
    def clean(self):
        from cleanup_service import cleanup_run
        return cleanup_run(self.run,self.work)
    def test_completed_removes_only_verified_disposable_copies(self):
        report=self.clean()
        self.assertEqual(report['status'],'cleaned');self.assertGreater(report['bytes_removed'],0)
        self.assertFalse((self.run/'input').exists());self.assertFalse((self.run/'sword').exists())
        for p in ('models/full.blend','job.json','pipeline-result.json','task.log','unknown.bin','source-config/mod.ini','cleanup-result.json'):self.assertTrue((self.run/p).is_file(),p)
        self.assertTrue((self.payload/'mod.ini').exists())
    def test_second_cleanup_is_idempotent(self):
        self.clean();report=self.clean();self.assertEqual(report['bytes_removed'],0);self.assertEqual(report['status'],'cleaned')
    def test_running_task_is_untouched(self):
        write_json(self.run/'pipeline-result.json',{'status':'running'})
        self.assertEqual(self.clean()['status'],'skipped');self.assertTrue((self.run/'sword').exists())
    def test_other_work_root_is_untouched(self):
        from cleanup_service import cleanup_run
        self.assertEqual(cleanup_run(self.run,self.root/'different')['status'],'skipped');self.assertTrue((self.run/'input').exists())
    def test_corrupted_backup_keeps_input(self):
        (self.payload/'mod.ini').write_text('changed')
        self.assertEqual(self.clean()['status'],'partial');self.assertTrue((self.run/'input/mod.ini').exists())
    def test_result_inside_input_prevents_input_deletion(self):
        path=self.run/'input/model.blend';path.write_bytes(b'keep')
        self.result['files']['other']={'path':str(path),'sha256':sha256(path)};write_json(self.run/'pipeline-result.json',self.result)
        self.assertEqual(self.clean()['status'],'partial');self.assertTrue(path.exists())
    def test_cancelled_task_copies_are_cleaned(self):
        write_json(self.run/'pipeline-result.json',{'status':'cancelled'})
        self.assertEqual(self.clean()['status'],'cleaned');self.assertTrue((self.run/'models/full.blend').exists())
    def test_model_hash_change_prevents_cleanup(self):
        (self.run/'models/full.blend').write_bytes(b'changed')
        self.assertEqual(self.clean()['status'],'skipped');self.assertTrue((self.run/'input').exists())
    def test_service_waits_for_worker_exit_then_cleans(self):
        import sys
        from unittest.mock import patch
        from task_service import TaskService
        script=self.root/'worker.py'
        event={'kind':'event','stage':'task','status':'passed','artifacts':{'run':str(self.run)}}
        script.write_text('import json\nprint('+repr(json.dumps(event))+',flush=True)\n')
        service=TaskService()
        with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
            service.start({},self.root,{'work_root':str(self.work)});service.thread.join(10)
        self.assertFalse(service.busy);self.assertFalse((self.run/'sword').exists())
        self.assertEqual(service.drain()[-1]['status'],'passed')
    def test_cancelled_service_cleans_after_process_stops(self):
        import sys,time
        from unittest.mock import patch
        from task_service import TaskService
        script=self.root/'worker.py';event={'kind':'event','stage':'prepare','artifacts':{'run':str(self.run)}}
        script.write_text('import time\nprint('+repr(json.dumps(event))+',flush=True)\ntime.sleep(120)\n')
        service=TaskService()
        with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
            task=service.start({},self.root,{'work_root':str(self.work)})
            deadline=time.monotonic()+5
            while not getattr(service,'run',None) and time.monotonic()<deadline:time.sleep(.02)
            service.cancel(task);service.thread.join(10)
        self.assertFalse(service.busy);self.assertFalse((self.run/'sword').exists())
        self.assertEqual(json.loads((self.run/'pipeline-result.json').read_text(encoding='utf8'))['status'],'cancelled')
        self.assertEqual(service.drain()[-1]['status'],'cancelled')
    def test_junction_target_is_never_followed(self):
        import os,subprocess,shutil
        outside=self.root/'outside';outside.mkdir();(outside/'keep.bin').write_bytes(b'keep')
        shutil.rmtree(self.run/'sword')
        if os.name=='nt':
            link=str(self.run/'sword').replace("'","''");dest=str(outside).replace("'","''")
            subprocess.run(['powershell','-NoProfile','-Command',f"New-Item -ItemType Junction -Path '{link}' -Target '{dest}' | Out-Null"],check=True)
        else:(self.run/'sword').symlink_to(outside,target_is_directory=True)
        self.assertEqual(self.clean()['status'],'partial');self.assertTrue((outside/'keep.bin').exists())
        self.assertTrue((self.run/'sword').exists())
    def test_sword_diagnostics_are_archived(self):
        (self.run/'sword/Logs').mkdir();(self.run/'sword/Logs/engine.log').write_text('diagnostic')
        (self.run/'sword/Configs').mkdir();(self.run/'sword/Configs/RunResult.json').write_text('{"result":1}')
        self.clean()
        self.assertEqual((self.run/'engine-diagnostics/Logs/engine.log').read_text(),'diagnostic')
        self.assertTrue((self.run/'engine-diagnostics/Configs/RunResult.json').exists())
    def test_reverse_leftover_is_cleaned_on_retry_without_input(self):
        self.clean();(self.run/'input-Reverse').mkdir();(self.run/'input-Reverse/tmp.buf').write_bytes(b'temp')
        self.clean();self.assertFalse((self.run/'input-Reverse').exists())
    def test_worker_crash_stops_descendants_before_cleanup(self):
        import sys,time
        from unittest.mock import patch
        from task_service import TaskService
        marker=self.root/'child-still-running';script=self.root/'crash.py'
        child='import time,pathlib;time.sleep(1);pathlib.Path('+repr(str(marker))+').write_text("alive");time.sleep(90)'
        event={'kind':'event','stage':'task','status':'failed','artifacts':{'run':str(self.run)}}
        write_json(self.run/'pipeline-result.json',{'status':'failed'})
        script.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nprint('+repr(json.dumps(event))+',flush=True)\nsys.exit(2)\n')
        service=TaskService()
        with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
            service.start({},self.root,{'work_root':str(self.work)});service.thread.join(10)
        time.sleep(1.1)
        self.assertFalse(marker.exists());self.assertFalse((self.run/'sword').exists())
    def test_inherited_child_pipe_does_not_hide_worker_crash(self):
        import sys
        from unittest.mock import patch
        from task_service import TaskService
        script=self.root/'crash-pipe.py';event={'kind':'event','stage':'task','status':'failed','artifacts':{'run':str(self.run)}}
        write_json(self.run/'pipeline-result.json',{'status':'failed'})
        script.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"],close_fds=False)\nprint('+repr(json.dumps(event))+',flush=True)\nsys.exit(2)\n')
        service=TaskService()
        with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
            task=service.start({},self.root,{'work_root':str(self.work)});service.thread.join(5)
            completed=not service.busy
            if not completed:service.cancel(task);service.thread.join(10)
        self.assertTrue(completed);self.assertFalse((self.run/'sword').exists())
    def test_library_inside_runtime_is_never_deleted(self):
        self.job['library_root']=str(self.run/'sword');write_json(self.run/'job.json',self.job)
        self.assertEqual(self.clean()['status'],'skipped');self.assertTrue((self.run/'sword/runtime.bin').exists())
    def test_event_processing_error_stops_worker_before_service_is_idle(self):
        import sys
        from unittest.mock import patch
        from task_service import TaskService
        script=self.root/'bad-event.py'
        script.write_text('import time\nprint(\'{"kind":"event","artifacts":5}\',flush=True)\ntime.sleep(90)\n')
        service=TaskService()
        with patch('task_service.worker_command',return_value=[sys.executable,str(script)]):
            service.start({},self.root,{'work_root':str(self.work)});service.thread.join(5)
        self.assertFalse(service.busy);self.assertIsNotNone(service.process.poll())
        self.assertIsNone(service.worker_tree.handle)
    def test_readonly_attribute_on_disposable_copy_is_cleaned(self):
        import os,stat
        if os.name!='nt':self.skipTest('Windows read-only attribute')
        (self.run/'sword').chmod(stat.S_IREAD)
        self.assertEqual(self.clean()['status'],'cleaned');self.assertFalse((self.run/'sword').exists())
