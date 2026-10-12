import base64
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
import archive_helper as helper

@unittest.skipUnless(Path(helper.DEFAULT_SEVEN_ZIP).is_file(),'本机7-Zip不存在')
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.password=uuid.uuid4().hex
  self.base=Path(self.temp.name);(self.base/'readme.txt').write_text('中文测试内容',encoding='utf-8')
  subprocess.run([helper.DEFAULT_SEVEN_ZIP,'a','-t7z','-p'+self.password,'-mhe=on',str(self.base/'test.7z'),str(self.base/'readme.txt')],check=True,stdout=subprocess.DEVNULL)
  (self.base/'test.7z').rename(self.base/'PC.exe')
  self.request={'archive':str(self.base/'PC.exe'),'settings':{'root':str(self.base/'games'),'password':self.password,'sevenZip':helper.DEFAULT_SEVEN_ZIP},'metadata':{'category':'SLG','title':'中文游戏测试','text':'测试介绍','source':'https://example.com','images':[]}}
 def test_disguised_exe_extract_and_preserve(self):
  original=(self.base/'PC.exe').read_bytes();result=helper.archive_game(self.request)
  dest=Path(result['path'])
  self.assertEqual(result['format'],'7z')
  self.assertEqual((dest/'readme.txt').read_text('utf-8'),'中文测试内容')
  self.assertTrue((dest/'介绍'/'介绍.html').is_file())
  self.assertEqual((self.base/'PC.exe').read_bytes(),original)
  with self.assertRaises(FileExistsError):helper.archive_game(self.request)
 def test_archive_wrapper_published_as_game_title(self):
  payload=self.base/'PC-AI';(payload/'Game').mkdir(parents=True)
  (payload/'Game'/'game.exe').write_bytes(b'game-test')
  (payload/'readme.txt').write_bytes(b'readme')
  archive=self.base/'wrapped.7z'
  subprocess.run([helper.DEFAULT_SEVEN_ZIP,'a','-t7z','-p'+self.password,str(archive),str(payload)],check=True,stdout=subprocess.DEVNULL)
  self.request['archive']=str(archive)
  result=helper.archive_game(self.request);dest=Path(result['path'])
  self.assertFalse((dest/'PC-AI').exists())
  self.assertEqual((dest/'Game'/'game.exe').read_bytes(),b'game-test')
  manifest=json.loads((dest/'验证记录.json').read_text('utf-8'))
  self.assertEqual(manifest['removedWrappers'],['PC-AI'])
  for member in manifest['files']:
   file=dest.joinpath(*helper.PureWindowsPath(member['path']).parts)
   self.assertEqual(helper.sha256_file(file),member['sha256'])
   self.assertTrue(member['archivePath'].startswith('PC-AI'))
 def test_wrong_password_no_game_created(self):
  self.request['settings']['password']='wrong'
  with self.assertRaises(ValueError):helper.archive_game(self.request)
  self.assertFalse((self.base/'games'/'SLG'/'中文游戏测试').exists())
 def test_idm_cleanup_only_after_verified_game(self):
  self.request['settings'].update(deleteArchive=True,idmFolder=str(self.base))
  self.request['idm']=True
  result=helper.archive_game(self.request)
  self.assertTrue(result['sourceDeleted']);self.assertFalse((self.base/'PC.exe').exists())
  self.assertTrue((Path(result['path'])/'验证记录.json').is_file())
 def test_image_failure_retains_source(self):
  self.request['settings'].update(deleteArchive=True,idmFolder=str(self.base));self.request['idm']=True
  self.request['metadata']['imageErrors']=['missing image']
  result=helper.archive_game(self.request)
  self.assertFalse(result['sourceDeleted']);self.assertTrue((self.base/'PC.exe').exists())
 def test_changed_source_refuses_cleanup(self):
  target=self.base/'verified-game';target.mkdir()
  source=self.base/'PC.exe';signature=helper.file_signature(source);digest=helper.sha256_file(source)
  source.write_bytes(b'replacement')
  with self.assertRaises(ValueError):helper.delete_verified_source(source,target,self.base,signature,digest)
  self.assertTrue(source.exists())
 def test_native_host_actual_stdio(self):
  stream=io.BytesIO();helper.write_message(stream,{'action':'archive',**self.request})
  result=subprocess.run([sys.executable,str(Path(helper.__file__))],input=stream.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
  responses=[];output=io.BytesIO(result.stdout)
  while (message:=helper.read_message(output)) is not None:responses.append(message)
  self.assertTrue(responses[-1]['ok']);self.assertIn('path',responses[-1]);self.assertTrue(any('progress' in m for m in responses))
  self.assertNotIn(self.password.encode(),result.stdout)
 def test_idm_native_prepare_poll_archive_cleanup_pipeline(self):
  folder=self.base/'programs';folder.mkdir();candidate=folder/'PC_2.exe'
  script="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import idm_bridge as idm;idm.DATA_ROOT=Path(sys.argv[2]);candidate=Path(sys.argv[3]);url='https://download.example/file?token=test';idm.read_records=lambda:[{'id':'new','urlHash':idm.url_hash(url),'status':3,'size':candidate.stat().st_size,'downloaded':candidate.stat().st_size}] if candidate.exists() else [];original=idm.poll_watch;idm.poll_watch=lambda *a,**kw:original(*a,**kw,stable_seconds=0);import archive_helper;archive_helper.main()"
  worker=subprocess.Popen([sys.executable,'-u','-c',script,str(Path(helper.__file__).parent),str(self.base/'watch-data'),str(candidate)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  self.addCleanup(lambda:worker.kill() if worker.poll() is None else None)
  def call(message):
   helper.write_message(worker.stdin,message)
   while True:
    answer=helper.read_message(worker.stdout)
    if not answer.get('progress'):return answer
  watch=call({'action':'prepare_idm','folder':str(folder),'expected':'PC.exe','jobId':'test-job'})
  self.assertTrue(watch['ok']);candidate.write_bytes((self.base/'PC.exe').read_bytes())
  import idm_bridge
  digest=idm_bridge.url_hash('https://download.example/file?token=test')
  self.assertFalse(call({'action':'poll_idm','token':watch['token'],'urlHashes':[digest]})['ready'])
  self.assertTrue(call({'action':'poll_idm','token':watch['token'],'urlHashes':[digest]})['ready'])
  self.request['settings'].update(idmFolder=str(folder),deleteArchive=True)
  result=call({'action':'archive_idm','token':watch['token'],'settings':self.request['settings'],'metadata':self.request['metadata']})
  self.assertTrue(result['ok'],result);self.assertTrue(result['sourceDeleted']);self.assertFalse(candidate.exists());self.assertTrue((self.base/'PC.exe').exists())
  worker.stdin.close();worker.wait(timeout=10);worker.stdout.close();worker.stderr.close()

if __name__=='__main__':unittest.main()
