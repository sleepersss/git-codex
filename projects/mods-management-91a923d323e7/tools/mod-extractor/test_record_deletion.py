import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from runner import Library,read_json,write_json,sha256
from record_deletion import delete_task,delete_asset


class RecordDeletionTests(unittest.TestCase):
    def test_another_editor_lock_prevents_task_deletion(self):
        from task_guard import task_guard
        with task_guard(self.run):
            with self.assertRaisesRegex(ValueError,'另一个窗口'):delete_task(self.run,self.work,self.lib.root)
        self.assertTrue(self.run.exists())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'work';self.work.mkdir();self.run=self.work/'mod-extraction-test-20261027-12345678'
        self.run.mkdir();self.lib=Library(self.root/'library')
        self.original=self.root/'original';self.original.mkdir();(self.original/'mod.ini').write_text('original')
        self.source=self.lib.source(self.original,'WW');self.full=self.run/'full.blend';self.full.write_bytes(b'BLENDER-model')
        self.asset=self.lib.register('WW','Fixture',self.source['id'],self.full)
        write_json(self.run/'job.json',{'source':str(self.original),'library_root':str(self.lib.root)})
        write_json(self.run/'pipeline-result.json',{'status':'passed','files':{'full':{'path':str(self.full),'sha256':sha256(self.full)}}})
    def tearDown(self):self.tmp.cleanup()
    def test_delete_task_removes_whole_task_and_keeps_library_and_original(self):
        result=delete_task(self.run,self.work,self.lib.root)
        self.assertFalse(self.run.exists());self.assertTrue(self.lib.find(self.asset['id'])[0].exists())
        self.assertEqual((self.original/'mod.ini').read_text(),'original')
        with zipfile.ZipFile(result['archive']) as z:
            self.assertEqual(z.read('payload/full.blend'),b'BLENDER-model')
            self.assertEqual(z.read('payload/job.json'),z.read('payload/job.json'))
        self.assertEqual(result['status'],'deleted')
    def test_running_task_and_arbitrary_directory_are_rejected(self):
        write_json(self.run/'pipeline-result.json',{'status':'running'})
        with self.assertRaises(ValueError):delete_task(self.run,self.work,self.lib.root)
        with self.assertRaises(ValueError):delete_task(self.work,self.work,self.lib.root)
        self.assertTrue(self.run.exists())
    def test_failed_archive_never_removes_task(self):
        with patch('record_deletion.archive_directory',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):delete_task(self.run,self.work,self.lib.root)
        self.assertTrue((self.run/'pipeline-result.json').exists())
    def test_asset_delete_updates_index_preserves_source_and_never_reuses_id(self):
        ident=self.asset['id'];path=self.lib.find(ident)[0].parent
        report=delete_asset(self.lib.root,ident)
        self.assertFalse(path.exists());self.assertEqual(self.lib.documents()[0],[])
        self.assertTrue(self.lib.find(self.source['id'],source=True)[0].exists())
        self.assertEqual(self.lib.allocate('WW'),'WW-000002')
        with zipfile.ZipFile(report['archive']) as z:self.assertEqual(z.read('payload/full.blend'),b'BLENDER-model')
        self.assertEqual(self.lib.audit()['errors'],[])
    def test_index_failure_restores_asset(self):
        path=self.lib.find(self.asset['id'])[0]
        with patch.object(Library,'rebuild',side_effect=OSError('index locked')):
            with self.assertRaises(OSError):delete_asset(self.lib.root,self.asset['id'])
        self.assertTrue(path.exists());self.assertEqual(self.lib.audit()['errors'],[])
    def test_shared_file_reference_prevents_asset_deletion(self):
        second=self.lib.register('WW','Other',self.source['id'],self.full)
        path,doc=self.lib.find(second['id']);doc['files']['shared']=self.asset['files']['full'];write_json(path,doc)
        with self.assertRaisesRegex(ValueError,'引用'):delete_asset(self.lib.root,self.asset['id'])
        self.assertTrue(self.lib.find(self.asset['id'])[0].exists())
    def test_failed_preparation_record_can_be_deleted_without_job(self):
        (self.run/'job.json').unlink();write_json(self.run/'pipeline-result.json',{'status':'failed','error':'prepare failed'})
        self.assertEqual(delete_task(self.run,self.work,self.lib.root)['status'],'deleted')
        self.assertFalse(self.run.exists())
    def test_nested_junction_is_rejected_without_touching_its_target(self):
        import os
        link=self.run/'linked-original'
        if os.name=='nt':
            import _winapi
            _winapi.CreateJunction(str(self.original),str(link))
        else:link.symlink_to(self.original,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'链接'):delete_task(self.run,self.work,self.lib.root)
            self.assertTrue((self.original/'mod.ini').exists());self.assertTrue(self.run.exists())
        finally:link.rmdir() if os.name=='nt' else link.unlink()
    def test_cache_junction_is_rejected_before_moving_asset(self):
        import os
        cache=self.lib.root/'cache';saved=self.lib.root/'original-cache';cache.rename(saved)
        outside=self.root/'outside-cache';outside.mkdir();metadata=self.lib.find(self.asset['id'])[0]
        if os.name=='nt':
            import _winapi
            _winapi.CreateJunction(str(outside),str(cache))
        else:cache.symlink_to(outside,target_is_directory=True)
        try:
            with self.assertRaises(ValueError):delete_asset(self.lib.root,self.asset['id'])
            self.assertTrue(metadata.exists(),'asset moved before rejecting linked staging path')
            self.assertEqual(list(outside.iterdir()),[])
        finally:
            cache.rmdir() if os.name=='nt' else cache.unlink();saved.rename(cache)


if __name__=='__main__':unittest.main()
