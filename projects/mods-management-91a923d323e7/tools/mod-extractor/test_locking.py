import unittest,tempfile,subprocess,sys
from pathlib import Path
from runner import Library,locked
class LockTests(unittest.TestCase):
    def test_process_death_releases_lock(self):
        with tempfile.TemporaryDirectory() as d:
            lib=Library(Path(d)/'library')
            script='import sys,os\nsys.path.insert(0,sys.argv[1])\nfrom runner import Library,locked\nwith locked(Library(sys.argv[2])):\n os._exit(0)'
            subprocess.run([sys.executable,'-c',script,str(Path(__file__).parent),str(lib.root)],check=True)
            with locked(lib):pass
