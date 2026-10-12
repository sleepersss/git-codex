import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
import idm_bridge as idm

class IDMTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.folder=self.base/'programs';self.folder.mkdir();self.data=self.base/'data'
  self.url='https://download.example/package?token=new'
 def record(self,size=5,status=3):return {'id':'12','urlHash':idm.url_hash(self.url),'size':size,'downloaded':size,'status':status}
 def prepare(self):
  with patch.object(idm,'read_records',return_value=[]):return idm.prepare_watch(str(self.folder),'PC-AI.exe','job',self.data)
 def test_names(self):
  self.assertTrue(idm.match_name('PC-AI_3.exe','PC-AI.exe'));self.assertFalse(idm.match_name('安卓.exe','PC-AI.exe'));self.assertFalse(idm.match_name('PC-AI.exe.part','PC-AI.exe'))
 def test_url_hash_matches_extension_encoding(self):
  import hashlib
  expected=hashlib.sha256(b'https://download.example/file?a=x%2Ay&b=one+two&t=~').hexdigest()
  self.assertEqual(idm.url_hash('https://DOWNLOAD.example/file?t=~&b=one%20two&a=x*y#ignored'),expected)
 def test_new_candidate_only_and_verified_source(self):
  (self.folder/'PC-AI.exe').write_bytes(b'old!!');watch=self.prepare();new=self.folder/'PC-AI_2.exe';new.write_bytes(b'new!!')
  with patch.object(idm,'read_records',return_value=[self.record()]):
   self.assertFalse(idm.poll_watch(watch['token'],[self.url],self.data)['ready'])
   result=idm.poll_watch(watch['token'],[self.url],self.data,stable_seconds=0)
  self.assertTrue(result['ready']);self.assertEqual(result['archive'],str(new));self.assertTrue((self.folder/'PC-AI.exe').exists())
 def test_wrong_source_or_incomplete_record_not_ready(self):
  watch=self.prepare();(self.folder/'PC-AI.exe').write_bytes(b'new!!')
  with patch.object(idm,'read_records',return_value=[self.record(status=0)]):self.assertFalse(idm.poll_watch(watch['token'],[self.url],self.data,stable_seconds=0)['ready'])
  with patch.object(idm,'read_records',return_value=[self.record()]):self.assertFalse(idm.poll_watch(watch['token'],['https://other.example/'],self.data,stable_seconds=0)['ready'])
 def test_multiple_candidates_stop(self):
  watch=self.prepare();(self.folder/'PC-AI.exe').write_bytes(b'new!!');(self.folder/'PC-AI_2.exe').write_bytes(b'new!!')
  with patch.object(idm,'read_records',return_value=[self.record()]):
   with self.assertRaises(ValueError):idm.poll_watch(watch['token'],[self.url],self.data,stable_seconds=0)
 def test_bad_token(self):
  with self.assertRaises(ValueError):idm.poll_watch('../outside',[],self.data)
 def test_old_file_even_changed_mtime_is_not_auto_claimed(self):
  old=self.folder/'PC-AI.exe';old.write_bytes(b'old!!');watch=self.prepare()
  import os
  os.utime(old,ns=(old.stat().st_atime_ns,old.stat().st_mtime_ns+1000000000))
  with patch.object(idm,'read_records',return_value=[self.record()]):
   for _ in range(2):self.assertFalse(idm.poll_watch(watch['token'],[self.url],self.data,stable_seconds=0)['ready'])

if __name__=='__main__':unittest.main()
