import unittest,tempfile
from pathlib import Path
from discovery import discover_mod

class DiscoveryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def mod(self,folder='其他人物',filename='Anything.ini',header='; WWMI BETA-2 INI'):
        p=self.root/folder;p.mkdir();(p/'Geometry').mkdir()
        (p/'Geometry/points.buf').write_bytes(b'\0'*36);(p/'Geometry/faces.buf').write_bytes(b'\0'*12)
        (p/filename).write_text(header+'\n[ResourcePositionBuffer]\nstride=12\nfilename=Geometry/points.buf\n[ResourceIndexBuffer]\nformat=R32_UINT\nfilename=Geometry/faces.buf\n[TextureOverrideComponent0]\nib=ResourceIndexBuffer\nvb0=ResourcePositionBuffer\ndrawindexed=3,0,0\n',encoding='utf-8')
        return p
    def test_no_character_whitelist(self):
        p=self.mod();r=discover_mod(p)
        self.assertEqual(r['candidates'][0]['ini'],'Anything.ini');self.assertEqual(r['game'],'WW')
        self.assertTrue(r['supported']);self.assertEqual(r['title'],'其他人物')
    def test_primary_ini_not_subvariant(self):
        p=self.mod(filename='mod.ini');sub=p/'无毛';sub.mkdir();(sub/'mod.ini').write_text((p/'mod.ini').read_text(encoding='utf-8'),encoding='utf-8')
        self.assertEqual(discover_mod(p)['candidates'][0]['ini'],'mod.ini')
    def test_resource_escape_not_allowed(self):
        p=self.mod();f=p/'Anything.ini';f.write_text(f.read_text(encoding='utf-8').replace('Geometry/points.buf','../outside.buf'),encoding='utf-8')
        self.assertFalse(discover_mod(p)['supported'])
        self.assertIn('外部',discover_mod(p)['message'])
    def test_unknown_game_requires_choice(self):
        p=self.mod(header='; exported mod')
        self.assertFalse(discover_mod(p)['supported'])
        self.assertTrue(discover_mod(p,game_hint='HSR')['supported'])
    def test_zip_named_directory_is_directory(self):
        self.assertTrue(discover_mod(self.mod(folder='别的人物.zip'))['supported'])
    def test_empty_or_menu_ini_not_a_mesh(self):
        (self.root/'menu.ini').write_text('[TextureOverride]\nhash=abcdef12\n')
        self.assertFalse(discover_mod(self.root)['supported'])
