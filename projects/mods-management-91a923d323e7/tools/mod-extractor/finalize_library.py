"""Import a verified task using the same policy as the desktop."""
import sys,json
from pathlib import Path
from runner import read_json
from library_service import import_result
run=Path(sys.argv[1]).resolve();job=read_json(run/'job.json')
print(json.dumps(import_result(Path(job['library_root']),run),ensure_ascii=False,indent=2))
