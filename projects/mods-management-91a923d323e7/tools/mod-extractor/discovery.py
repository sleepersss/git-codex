"""Read-only detection of indexed 3Dmigoto resources, independent of character names."""
from pathlib import Path
import re,os

def parse_ini(path):
    text=Path(path).read_bytes().decode('utf-8-sig',errors='replace')
    sections={};current=None
    for line in text.splitlines():
        line=line.split(';',1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            current=line[1:-1];sections.setdefault(current,[])
        elif current and '=' in line:
            key,value=line.split('=',1);sections[current].append((key.strip().lower(),value.strip()))
    return text,sections

def inspect_ini(root,path):
    text,sections=parse_ini(path);resources={};errors=[]
    for name,rows in sections.items():
        if not name.lower().startswith('resource'):continue
        values=dict(rows)
        if 'format' in values:values['format']=values['format'].upper().removeprefix('DXGI_FORMAT_')
        if 'filename' not in values:continue
        target=(path.parent/values['filename'].replace('\\','/')).resolve()
        if not target.is_relative_to(root):errors.append('配置引用来源文件夹外部文件：'+values['filename']);continue
        resources[name.lower()]={'name':name,'file':str(target.relative_to(root)),**values}
    vb0={re.sub(r'^(?:ref|copy)\s+','',v,flags=re.I).lower() for rows in sections.values() for k,v in rows if k=='vb0'}
    position=[r for r in resources.values() if 'position' in r['name'].lower() or r['name'].lower() in vb0]
    index=[r for r in resources.values() if 'index' in r['name'].lower() or r.get('format') in ('R32_UINT','R16_UINT')]
    draws=[]
    for section,rows in sections.items():
        for key,value in rows:
            if key!='drawindexed':continue
            if value.lower()=='auto':
                draws.append({'section':section,'auto':True});continue
            m=re.fullmatch(r'(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)',value)
            if m and int(m[1])>0:draws.append({'section':section,'count':int(m[1]),'start':int(m[2]),'base':int(m[3])})
    missing=[r['file'] for r in position+index if not (root/r['file']).is_file()]
    game='WW' if re.search(r'WWMI|required_wwmi_version',text,re.I) else 'HSR' if re.search(r'\bHSR\b|SRMI',text,re.I) else 'ZZZ' if re.search(r'\bZZZ\b|ZZMI',text,re.I) else None
    if not game:
        s=str(root).lower();game='HSR' if 'star rail' in s else 'ZZZ' if 'zenless' in s else 'WW' if 'wuthering waves' in s else None
    valid=bool(position and index and draws and not errors and not missing)
    return {'ini':path.relative_to(root).as_posix(),'resources':resources,'draws':draws,'game':game,'valid':valid,
        'errors':errors or (['模型缓冲区缺失：'+', '.join(missing)] if missing else []),'sections':sections}

def discover_mod(source,game_hint=None):
    root=Path(source).resolve();result={'title':root.name,'supported':False,'game':None,'candidates':[],'message':'请选择包含模型配置的 Mod 文件夹。'}
    if not root.is_dir():return result
    candidates=[]
    for folder,dirs,files in os.walk(root,followlinks=False):
        base=Path(folder)
        dirs[:]=[d for d in dirs if not (base/d).is_symlink() and not (hasattr(Path,'is_junction') and (base/d).is_junction())] if len(base.relative_to(root).parts)<5 else []
        for filename in files:
            path=base/filename
            if path.suffix.lower()!='.ini' or path.is_symlink():continue
            try:candidates.append(inspect_ini(root,path))
            except OSError:continue
            if len(candidates)>=200:break
        if len(candidates)>=200:break
    candidates.sort(key=lambda c:(len(Path(c['ini']).parts),not c['valid'],Path(c['ini']).name.lower()!='mod.ini',c['ini']))
    result['candidates']=candidates
    if not candidates:return result
    best=next((c for c in candidates if c['valid']),candidates[0]);result['selected_ini']=best['ini']
    result['game']=game_hint or best['game']
    result['supported']=best['valid'] and bool(result['game'])
    result['message']=best['errors'][0] if best['errors'] else '已识别配置：'+best['ini'] if result['supported'] else '无法识别游戏，请选择游戏。' if best['valid'] else '配置未包含可提取的索引模型资源。'
    return result
