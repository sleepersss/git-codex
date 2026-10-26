"""Separate bundled code, external tools, and writable user data."""
import os,sys,json
from pathlib import Path
APP_VERSION='3.3-r6'

def resource_root():
    return Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]

def default_config_path():
    if getattr(sys,'frozen',False):
        portable=Path(sys.executable).parent/'settings.json'
        if portable.is_file():return portable
        return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ModAssetExtractor/settings.json'
    return Path(__file__).with_name('config.json')

def resolve_paths(config_path=None):
    path=Path(config_path) if config_path else default_config_path()
    template=resource_root()/'tools/mod-extractor/config.json'
    cfg=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    if not cfg and template.is_file():cfg=json.loads(template.read_text(encoding='utf-8-sig'))
    base=(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ModAssetExtractor/data'
          if getattr(sys,'frozen',False) else resource_root())
    cfg.setdefault('work_root',str(base/'work'));cfg.setdefault('library_root',str(base/'model-library'))
    cfg['config_path']=str(path);return cfg

def check_dependencies(config):
    items=[('Blender','blender',None),('Sword','sword_root','Plugins/3Dmigoto-Sword-Lv5.vmp.exe'),
           ('Herta','herta_parent','HertaBlender/__init__.py')]
    result=[]
    for label,key,suffix in items:
        value=config.get(key,'');p=Path(value)/suffix if suffix else Path(value)
        result.append({'name':label,'key':key,'ok':bool(value) and p.is_file(),'path':str(p)})
    return result

def worker_command(job,frozen=None):
    frozen=getattr(sys,'frozen',False) if frozen is None else frozen
    return [str(Path(sys.executable).with_name('ModExtractorWorker.exe')),'--worker-task',str(job)] if frozen else [sys.executable,str(Path(__file__).with_name('desktop.py')),'--worker-task',str(job)]

