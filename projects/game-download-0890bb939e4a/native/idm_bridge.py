"""Read-only IDM completion records and scoped, persistent download watches."""
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, parse_qsl, urlencode
import uuid

DATA_ROOT=Path(__file__).resolve().parent/'data'/'idm'

def url_hash(url):
    value=urlsplit(url)
    normalized=value.scheme.lower()+'://'+value.netloc.lower()+value.path+'?'+urlencode(sorted(parse_qsl(value.query,keep_blank_values=True)))
    return hashlib.sha256(normalized.encode()).hexdigest()

def number(value):
    if isinstance(value,bytes):return int.from_bytes(value,'little')
    return int(value or 0)

def read_records():
    try: import winreg
    except ImportError:return []
    records=[]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\DownloadManager') as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                name=winreg.EnumKey(root,index)
                if not name.isdigit():continue
                try:
                    with winreg.OpenKey(root,name) as key:
                        def get(field):
                            try:return winreg.QueryValueEx(key,field)[0]
                            except FileNotFoundError:return None
                        url=get('Url0')
                        if not isinstance(url,str) or not url.startswith('https://'):continue
                        records.append({'id':name,'urlHash':url_hash(url),'status':number(get('Status')),'size':number(get('FileSize')),'downloaded':number(get('Downloaded'))})
                except OSError:continue
    except FileNotFoundError:pass
    return records

def folder_path(folder):
    path=Path(folder)
    if not path.is_absolute() or not path.is_dir():raise ValueError('IDM目录不存在，请检查设置')
    for parent in (path,*path.parents):
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):raise ValueError('IDM目录不能含链接或目录联接')
    return path.resolve()

def match_name(name,expected):
    expected=Path(expected)
    return bool(re.fullmatch(re.escape(expected.stem)+r'(?:_\d+| \(\d+\))?'+re.escape(expected.suffix),name,re.I))

def stamp(path):
    info=path.stat()
    return [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns]

def files(folder):
    result={}
    for path in folder.iterdir():
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {'.exe','.7z','.rar','.zip'}:
            result[path.name]=stamp(path)
    return result

def record_stamp(record):return [record['urlHash'],record['status'],record['size'],record['downloaded']]

def save(state,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');temp.replace(path)

def load(token,state_dir=None):
    if not re.fullmatch('[a-f0-9]{32}',str(token)):raise ValueError('无效IDM监视令牌')
    path=(Path(state_dir) if state_dir else DATA_ROOT)/(token+'.json')
    return json.loads(path.read_text('utf-8')),path

def prepare_watch(folder,expected,job_id,state_dir=None):
    root=folder_path(folder)
    if Path(expected).name!=expected or Path(expected).suffix.lower() not in {'.exe','.7z','.rar','.zip'}:raise ValueError('不支持的IDM文件名')
    token=uuid.uuid4().hex
    state={'folder':str(root),'expected':expected,'jobId':job_id,'created':time.time(),'baseline':files(root),'records':{r['id']:record_stamp(r) for r in read_records()},'stable':{}}
    path=(Path(state_dir) if state_dir else DATA_ROOT)/(token+'.json');save(state,path)
    return {'ok':True,'token':token,'folder':str(root)}

def poll_watch(token,urls,state_dir=None,stable_seconds=5):
    state,path=load(token,state_dir)
    root=folder_path(state['folder']);now=time.time()
    if now-state['created']>86400:raise ValueError('IDM等待超过24小时，请确认下载后手动关联')
    hashes={u if re.fullmatch('[a-f0-9]{64}',u) else url_hash(u) for u in urls if isinstance(u,str) and (u.startswith('https://') or re.fullmatch('[a-f0-9]{64}',u))}
    completed=[r for r in read_records() if r['urlHash'] in hashes and r['status']==3 and r['size']>0 and r['downloaded']>=r['size'] and state['records'].get(r['id'])!=record_stamp(r)]
    candidates=[]
    for name,signature in files(root).items():
        if not match_name(name,state['expected']) or name in state['baseline']:continue
        if not any(r['size']==signature[2] for r in completed):continue
        candidates.append((name,signature))
    if len(candidates)>1:raise ValueError('出现多个同名新IDM文件，无法唯一关联；请在任务页手动选择')
    if candidates:
        name,signature=candidates[0];previous=state['stable'].get(name)
        if not previous or previous['signature']!=signature:state['stable']={name:{'signature':signature,'since':now}}
        elif now-previous['since']>=stable_seconds:
            state['ready']={'archive':str(root/name),'signature':signature};save(state,path)
            return {'ok':True,'ready':True,'archive':str(root/name)}
    else:state['stable']={}
    save(state,path)
    return {'ok':True,'ready':False,'note':'等待IDM完成并落盘' if hashes else '等待IDM下载来源；未捕获来源时可手动关联'}

def claim_ready(token):
    state,path=load(token)
    ready=state.get('ready')
    if not ready:raise ValueError('IDM文件尚未验证完成')
    archive=Path(ready['archive']);root=folder_path(state['folder'])
    if archive.parent.resolve()!=root or archive.is_symlink() or stamp(archive)!=ready['signature']:raise ValueError('IDM文件在验证后发生变化，未处理')
    return state,archive

def list_files(folder,expected):
    root=folder_path(folder)
    return [{'path':str(root/name),'size':sig[2],'modified':sig[3]/1000000} for name,sig in sorted(files(root).items(),key=lambda item:item[1][3],reverse=True) if match_name(name,expected)]
