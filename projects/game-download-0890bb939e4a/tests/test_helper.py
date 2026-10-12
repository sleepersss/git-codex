import sys, unittest, tempfile, io, json, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
import archive_helper as helper

class HelperTests(unittest.TestCase):
 def test_single_wrapper_removed_and_manifest_remapped(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'PC-AI'/'Game').mkdir(parents=True)
   (root/'PC-AI'/'Game'/'game.exe').write_bytes(b'game')
   (root/'PC-AI'/'readme.txt').write_text('readme')
   entries=[{'Path':'PC-AI/Game/game.exe','Size':'4'},{'Path':'PC-AI/readme.txt','Size':'6'}]
   members=helper.verify_extracted(root,entries)
   removed=helper.normalize_game_layout(root,members)
   self.assertEqual(removed,['PC-AI']);self.assertFalse((root/'PC-AI').exists())
   self.assertEqual((root/'Game'/'game.exe').read_bytes(),b'game')
   self.assertEqual(members[0]['path'],'Game\\game.exe')
   self.assertEqual(members[0]['archivePath'],'PC-AI/Game/game.exe')
 def test_multiple_payload_roots_preserved(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'one').mkdir();(root/'two').mkdir()
   self.assertEqual(helper.normalize_game_layout(root,[]),[])
 def test_windows_name(self):
  self.assertEqual(helper.safe_name('游戏:名称?'), '游戏_名称_')
  for name in ('..','CON','NUL.txt',''):
   with self.assertRaises(ValueError): helper.safe_name(name)

 def test_archive_paths(self):
  helper.validate_entries([{'Path':'游戏/Game.exe','Folder':'-'}])
  for path in ('../bad','C:/bad','/bad','a/../../bad','a:file','a/NUL.txt','a\\..\\bad'):
   with self.assertRaises(ValueError): helper.validate_entries([{'Path':path}])
  with self.assertRaises(ValueError): helper.validate_entries([{'Path':'a','Symbolic Link':'b'}])

 def test_duplicate_target(self):
  with tempfile.TemporaryDirectory() as temp:
   (Path(temp)/'RPG'/'测试').mkdir(parents=True)
   with self.assertRaises(FileExistsError): helper.target_path(temp,'RPG','测试')

 def test_category(self):
  with tempfile.TemporaryDirectory() as temp:
   with self.assertRaises(ValueError): helper.target_path(temp,'../bad','测试')

 def test_protocol(self):
  data={'action':'ping','文字':'中文'}
  stream=io.BytesIO(); helper.write_message(stream,data); stream.seek(0)
  self.assertEqual(helper.read_message(stream), data)
  with self.assertRaises(ValueError): helper.read_message(io.BytesIO(struct.pack('<I',0xffffffff)))

 def test_description_escape(self):
  with tempfile.TemporaryDirectory() as temp:
   helper.write_description(Path(temp),{'title':'<script>','text':'<&','source':'https://example.com'})
   html=(Path(temp)/'介绍'/'介绍.html').read_text('utf-8')
   self.assertNotIn('<script>',html); self.assertIn('&lt;script&gt;',html)

if __name__ == '__main__': unittest.main()
