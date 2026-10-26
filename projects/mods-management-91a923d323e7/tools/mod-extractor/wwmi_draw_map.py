"""Map every labelled WWMI drawindexed to a Sword reverse component file."""
import re
from pathlib import Path

COMPONENT=re.compile(r'\[TextureOverrideComponent(\d+)\](.*?)(?=\n\[|\Z)',re.S|re.I)
DRAW=re.compile(r'drawindexed\s*=\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)',re.I)
STATIC_VAR=re.compile(r'\$\w+')


def _conditions(frames):
    return [c for f in frames for c in f['current']]


def parse_component_draws(ini_path):
    """Return {component_id: [draw, ...]} in source order. One Sword Component N.M per draw."""
    text=Path(ini_path).read_bytes().decode('utf-8-sig',errors='replace')
    components={}
    for match in COMPONENT.finditer(text):
        cid=match[1];draws=[];label='';frames=[]
        for raw in match[2].splitlines():
            line=raw.strip()
            if re.match(r';\s*Draw\b',line,re.I):
                label=line.lstrip('; ').strip();continue
            code=line.split(';',1)[0].strip()
            if not code:continue
            lowered=code.casefold()
            if lowered.startswith('if '):
                expression=code[3:].strip();frames.append({'previous':[expression],'current':[expression]});continue
            if lowered.startswith(('elseif ','elif ','else if ')):
                if frames:
                    frame=frames[-1];expression=re.sub(r'^(?:elseif|elif|else\s+if)\s+','',code,flags=re.I).strip()
                    frame['current']=['not ('+' || '.join(frame['previous'])+')',expression]
                    frame['previous'].append(expression)
                continue
            if lowered=='else':
                if frames:frames[-1]['current']=['not ('+' || '.join(frames[-1]['previous'])+')']
                continue
            if lowered=='endif':
                if frames:frames.pop()
                continue
            found=DRAW.fullmatch(code)
            if not found:continue
            draws.append({'component':int(cid),'index':len(draws),'count':int(found[1]),'start':int(found[2]),
                'base':int(found[3]),'label':label or ('Component %s.%s'%(cid,len(draws))),
                'section':'TextureOverrideComponent'+cid,'conditions':_conditions(frames)})
            label=''
        components[cid]=draws
    return components


def expected_fmt_count(components):
    return sum(len(rows) for rows in components.values())


def static_draw_conditions(conditions):
    """Keep source $variable tests; drop runtime texture/format probes."""
    return [c for c in conditions if STATIC_VAR.search(c) and '->' not in c]


def select_reverse_layout(reverse_root,expected):
    reverse_root=Path(reverse_root)
    if not reverse_root.is_dir():
        raise ValueError('Sword 逆向输出目录不存在：'+str(reverse_root))
    candidates=[]
    for folder in reverse_root.iterdir():
        if not folder.is_dir():continue
        complete=0
        for fmt in folder.glob('Component *.fmt'):
            ib,vb=fmt.with_suffix('.ib'),fmt.with_suffix('.vb')
            if ib.is_file() and vb.is_file() and ib.stat().st_size>0 and vb.stat().st_size>0:complete+=1
        candidates.append((folder,complete))
    matching=[item for item in candidates if item[1]==expected]
    if not matching:
        detail=', '.join('%s:%s'%(folder.name,count) for folder,count in candidates) or '无'
        raise ValueError('Sword 逆向布局数量与源绘制范围不一致，需要 %s 组，实际：%s'%(expected,detail))
    def score(item):
        name=item[0].name;suffix=name.rsplit('_',1)[-1]
        return (0 if name.startswith('GPU') else 1,0 if suffix in ('0','4') else 1,name)
    matching.sort(key=score)
    return matching[0][0]


def component_fmt(layout,component,index):
    return Path(layout)/('Component %s.%s.fmt'%(component,index))
