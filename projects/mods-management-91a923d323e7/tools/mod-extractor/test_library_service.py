import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from library_service import archive_rejected_body,list_assets,import_result
from runner import Library,read_json,sha256

class MigrationTests(unittest.TestCase):
    def test_runtime_partial_result_cannot_be_imported_as_verified_full(self):
        import tempfile
        from runner import write_json
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);write_json(r/'pipeline-result.json',{'status':'passed','full_status':'partial','body_status':'unverified'})
            write_json(r/'job.json',{})
            with self.assertRaisesRegex(ValueError,'完整模型'):
                import_result(r/'library',r)
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.lib=Library(self.root/'library')
        src=self.root/'source';src.mkdir();(src/'mod.ini').write_text('fixture')
        s=self.lib.source(src,'WW');full=self.root/'full.blend';full.write_bytes(b'BLENDER-v300full geometry')
        body=self.root/'body.blend';body.write_bytes(b'BLENDER-v300partial body')
        self.doc=self.lib.register('WW','Iuno',s['id'],full,body)
        self.ident=self.doc['id'];self.hash=sha256(self.lib.inside(self.doc['files']['full']['path']))
    def tearDown(self):self.t.cleanup()
    def test_hsr_generic_preview_names_match_converted_source_axes(self):
        from library_service import preview_views
        self.assertEqual(preview_views({'library_game':'HSR'},{'profile':'auto'})['front'],'front')
        self.assertEqual(preview_views({'library_game':'HSR'},{'profile':'auto'})['back'],'back')
        self.assertEqual(preview_views({'library_game':'WW'},{'profile':'denia'})['front'],'back')
    def test_archives_once_preserves_full(self):
        for _ in range(2):archive_rejected_body(self.lib.root,self.ident,{'reason_code':'body_gaps','message':'缺脚'})
        _,doc=self.lib.find(self.ident)
        self.assertNotIn('body',doc['files']);self.assertIn('rejected_body',doc['files'])
        self.assertEqual(sha256(self.lib.inside(doc['files']['full']['path'])),self.hash)
        self.assertTrue(self.lib.inside(doc['files']['rejected_body']['path']).is_file())
        self.assertEqual(list_assets(self.lib.root,body_status='available'),[])
        self.assertEqual(self.lib.audit()['errors'],[])
    def test_failed_write_preserves_active_file_until_recovery(self):
        with patch('library_service.commit_metadata',side_effect=OSError('write denied')):
            with self.assertRaises(OSError):archive_rejected_body(self.lib.root,self.ident,{'reason_code':'body_gaps'})
        _,doc=self.lib.find(self.ident)
        self.assertTrue(self.lib.inside(doc['files']['body']['path']).is_file())
        archive_rejected_body(self.lib.root,self.ident,{'reason_code':'body_gaps'})
        self.assertEqual(self.lib.audit()['errors'],[])
    def test_task_cannot_import_into_different_library(self):
        from runner import write_json
        run=self.root/'run';run.mkdir()
        write_json(run/'job.json',{'library_root':str(self.root/'other-library'),'library_game':'WW','source_id':self.doc['source_id']})
        write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified'})
        with self.assertRaisesRegex(ValueError,'素材库'):
            import_result(self.lib.root,run)
    def test_failed_import_finalization_resumes(self):
        from runner import write_json
        import shutil
        run=self.root/'task';(run/'models').mkdir(parents=True)
        full=run/'models/full.blend';shutil.copy2(self.lib.inside(self.doc['files']['full']['path']),full)
        _,source=self.lib.find(self.doc['source_id'],source=True)
        write_json(run/'job.json',{'library_root':str(self.lib.root),'library_game':'WW','source_id':source['id'],
            'source_manifest_sha256':source['manifest_sha256'],'name':'iuno'})
        write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'abandoned',
            'body_reason':{'message':'缺脚'},'files':{'full':{'path':str(full),'sha256':sha256(full)}}})
        # Recreate a full-only unfinished registration, like a crash after register().
        path,doc=self.lib.find(self.ident);doc['files'].pop('body');write_json(path,doc)
        with patch('library_service.commit_metadata',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):import_result(self.lib.root,run)
        result=import_result(self.lib.root,run)
        self.assertEqual(result['extraction']['body_status'],'abandoned')
        self.assertEqual(result['extraction']['body_reason']['message'],'缺脚')
    def test_different_configurations_keep_separate_assets(self):
        from runner import write_json
        _,source=self.lib.find(self.doc['source_id'],source=True)
        ids=[]
        for configuration in ('a.ini','variant/b.ini'):
            run=self.root/configuration.replace('/','_');run.mkdir();full=run/'full.blend';full.write_bytes(b'BLENDER'+configuration.encode())
            write_json(run/'job.json',{'library_root':str(self.lib.root),'library_game':'WW','source_id':source['id'],
                'source_manifest_sha256':source['manifest_sha256'],'name':'auto-any','character':'Other','configuration':configuration})
            write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'abandoned','body_reason':{},
                'default_display':{'status':'unresolved','unresolved_draws':2},
                'verification':{'fingerprints':{'mesh':configuration}},'files':{'full':{'path':str(full),'sha256':sha256(full)}}})
            result=import_result(self.lib.root,run);ids.append(result['id'])
            self.assertEqual(result['extraction']['configuration'],configuration)
            self.assertEqual(result['extraction']['default_display']['status'],'unresolved')
            self.assertEqual(import_result(self.lib.root,run)['id'],result['id'])
        self.assertNotEqual(ids[0],ids[1]);self.assertNotIn(self.ident,ids)
    def test_main_ini_configuration_reuses_source_without_configuration(self):
        from runner import write_json
        path,doc=self.lib.find(self.ident)
        doc['extraction']['body_status']='available'
        write_json(path,doc)
        run=self.root/'gui';(run/'models').mkdir(parents=True)
        full=run/'models/full.blend';full.write_bytes(b'BLENDER-gui-full')
        body=run/'models/body.blend';body.write_bytes(b'BLENDER-gui-body')
        _,source=self.lib.find(self.doc['source_id'],source=True)
        write_json(run/'job.json',{'library_root':str(self.lib.root),'library_game':'WW','source_id':source['id'],
            'source_manifest_sha256':source['manifest_sha256'],'name':'auto-any','character':'锁暝','configuration':'mod1.ini'})
        write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'available',
            'body_reason':{'reason_code':'body_verified'},'body_fingerprints':{'skin':'same'},
            'files':{'full':{'path':str(full),'sha256':sha256(full)},'body':{'path':str(body),'sha256':sha256(body)}}})
        path,doc=self.lib.find(self.ident);doc['extraction']['body_fingerprints']={'skin':'same'};write_json(path,doc)
        result=import_result(self.lib.root,run)
        self.assertEqual(result['id'],self.ident)

    def test_same_source_body_fingerprints_reuse_existing_record(self):
        from runner import write_json
        import shutil
        run=self.root/'gui-rerun';(run/'models').mkdir(parents=True)
        full=run/'models/full.blend';full.write_bytes(b'BLENDER-v300full geometry different bytes')
        body=run/'models/body.blend';body.write_bytes(b'BLENDER-v300partial body different bytes')
        _,source=self.lib.find(self.doc['source_id'],source=True)
        fingerprints={'skin':'verified'}
        path,doc=self.lib.find(self.ident)
        doc['extraction']['body_status']='available'
        doc['extraction']['body_fingerprints']=fingerprints
        write_json(path,doc)
        write_json(run/'job.json',{'library_root':str(self.lib.root),'library_game':'WW','source_id':source['id'],
            'source_manifest_sha256':source['manifest_sha256'],'name':'auto-any','character':'锁暝'})
        write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'available',
            'body_reason':{'reason_code':'body_verified','message':'ok'},'body_fingerprints':fingerprints,
            'files':{'full':{'path':str(full),'sha256':sha256(full)},'body':{'path':str(body),'sha256':sha256(body)}}})
        result=import_result(self.lib.root,run)
        self.assertEqual(result['id'],self.ident)
        self.assertEqual(result['files']['body']['sha256'],self.doc['files']['body']['sha256'])

    def test_complete_body_upgrades_full_only_record_and_keeps_history(self):
        from runner import write_json
        import shutil
        archive_rejected_body(self.lib.root,self.ident,{'message':'old unverified policy'})
        run=self.root/'upgrade';run.mkdir();full=run/'full.blend';shutil.copy2(self.lib.inside(self.doc['files']['full']['path']),full)
        body=run/'body.blend';body.write_bytes(b'BLENDER-complete-new-source-body')
        _,source=self.lib.find(self.doc['source_id'],source=True)
        write_json(run/'job.json',{'library_root':str(self.lib.root),'library_game':'WW','source_id':source['id'],'source_manifest_sha256':source['manifest_sha256'],'name':'iuno'})
        write_json(run/'pipeline-result.json',{'status':'passed','full_status':'verified','body_status':'available','body_reason':{'message':'actual body checked'},
            'body_fingerprints':{'skin':'verified'},'files':{'full':{'path':str(full),'sha256':sha256(full)},'body':{'path':str(body),'sha256':sha256(body)}}})
        result=import_result(self.lib.root,run)
        self.assertEqual(result['id'],self.ident);self.assertIn('body',result['files']);self.assertIn('rejected_body',result['files'])
        self.assertEqual(result['files']['full']['sha256'],self.hash);self.assertEqual(result['extraction']['body_status'],'available')
        self.assertNotIn('裸模已放弃',result['body']['tags'])
        self.assertEqual(import_result(self.lib.root,run)['id'],self.ident)
