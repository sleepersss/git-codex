"""Re-selecting an archived source reuses its identity and repairs only its cache."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from runner import Library,read_json,write_json,inventory,prepare


class ArchivedSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'selected-mod';self.source.mkdir();(self.source/'mod.ini').write_text('[Constants]\n$x=0')
        (self.source/'mesh.buf').write_bytes(b'original buffer')
        self.lib=Library(self.root/'library');self.doc=self.lib.source(self.source,'WW')
        self.path=self.lib.find(self.doc['id'],source=True)[0]
        doc=read_json(self.path);doc['archive']={'archive_id':'sources-WW-test','filename':'sources-WW-test.zip',
            'archive_sha256':'archived-proof','loose_payload_present':False,'upload_status':'pending_user_upload'}
        doc['history'].append({'action':'cold_archive','at':'fixture'})
        write_json(self.path,doc);self.archived=copy.deepcopy(doc)
        shutil.rmtree(self.lib.inside(doc['payload']))
    def tearDown(self):self.tmp.cleanup()
    def test_reselected_archived_source_restores_exact_bytes_and_same_id(self):
        before=inventory(self.source);result=self.lib.source(self.source,'WW')
        self.assertEqual(result['id'],self.doc['id'])
        self.assertEqual(inventory(self.lib.inside(result['payload'])),before)
        self.assertEqual(inventory(self.source),before)
        saved=read_json(self.path);self.assertTrue(saved['archive']['loose_payload_present'])
        self.assertEqual(saved['archive']['archive_sha256'],'archived-proof')
        self.assertEqual(saved['history'][:len(self.archived['history'])],self.archived['history'])
        self.assertEqual(len(self.lib.documents()[1]),1)
        count=len(saved['history']);self.lib.source(self.source,'WW')
        self.assertEqual(len(read_json(self.path)['history']),count)
    def test_existing_corrupt_payload_is_never_overwritten(self):
        payload=self.lib.inside(self.doc['payload']);shutil.copytree(self.source,payload)
        (payload/'mesh.buf').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'哈希'):self.lib.source(self.source,'WW')
        self.assertEqual((payload/'mesh.buf').read_bytes(),b'corrupt')
    def test_failed_restore_copy_preserves_archived_metadata_and_leaves_no_payload(self):
        before=self.path.read_bytes()
        with patch('library.shutil.copytree',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.lib.source(self.source,'WW')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(self.lib.inside(self.doc['payload']).exists())
    def test_metadata_write_failure_rolls_back_source_payload_and_metadata(self):
        before=self.path.read_bytes()
        with patch('library.write_json',side_effect=OSError('metadata locked')):
            with self.assertRaises(OSError):self.lib.source(self.source,'WW')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(self.lib.inside(self.doc['payload']).exists())
    def test_reusing_source_does_not_rebuild_unrelated_library_records(self):
        with patch.object(Library,'rebuild',side_effect=ValueError('unrelated record incomplete')) as rebuild:
            result=self.lib.source(self.source,'WW')
        self.assertEqual(result['id'],self.doc['id']);rebuild.assert_not_called()
    def test_restoration_preserves_registered_model_bytes_and_metadata(self):
        full=self.root/'full.blend';full.write_bytes(b'BLENDER-source-model')
        asset=self.lib.register('WW','Fixture',self.doc['id'],full)
        metadata=self.lib.find(asset['id'])[0];before=metadata.read_bytes()
        self.lib.source(self.source,'WW')
        self.assertEqual(metadata.read_bytes(),before)
        self.assertEqual(self.lib.inside(asset['files']['full']['path']).read_bytes(),full.read_bytes())
    def test_modified_source_does_not_restore_or_overwrite_archived_identity(self):
        (self.source/'mesh.buf').write_bytes(b'changed source')
        result=self.lib.source(self.source,'WW')
        self.assertNotEqual(result['id'],self.doc['id'])
        self.assertFalse(self.lib.inside(self.doc['payload']).exists())
        self.assertEqual(read_json(self.path),self.archived)
    def test_missing_unarchived_backup_is_not_silently_replaced(self):
        doc=read_json(self.path);doc.pop('archive');write_json(self.path,doc)
        with self.assertRaises(FileNotFoundError):self.lib.source(self.source,'WW')
        self.assertFalse(self.lib.inside(self.doc['payload']).exists())
    def test_prepare_can_reuse_archived_source_and_keeps_source_manifest(self):
        sword=self.root/'sword';(sword/'Plugins').mkdir(parents=True);(sword/'Configs').mkdir()
        (sword/'Plugins/3Dmigoto-Sword-Lv5.vmp.exe').touch();write_json(sword/'Configs/Settings.json',{})
        herta=self.root/'herta/HertaBlender';herta.mkdir(parents=True);(herta/'__init__.py').touch()
        blender=self.root/'blender.exe';blender.touch()
        cfg={'work_root':str(self.root/'work'),'library_root':str(self.lib.root),'sword_root':str(sword),
            'herta_parent':str(herta.parent),'blender':str(blender)}
        with patch('runner.resolve_paths',return_value=cfg):result=prepare('fixture',self.source,'WW','mod.ini')
        job=read_json(Path(result['run'])/'job.json')
        self.assertEqual(job['source_id'],self.doc['id'])
        self.assertEqual(job['source_manifest_sha256'],self.doc['manifest_sha256'])
        self.assertEqual(inventory(Path(result['run'])/'input'),inventory(self.source))


if __name__=='__main__':unittest.main()
