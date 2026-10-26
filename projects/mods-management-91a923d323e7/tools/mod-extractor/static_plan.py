"""Enumerate source geometry branches without executing shaders or Mod code."""
from pathlib import Path
import re,json
from discovery import inspect_ini
from body_selection import draw_metadata,evaluate_condition,evaluate_static_value

SLOTS=('ib','vb0','vb1','vb2','vb3','vb4')

def reference(value):return re.sub(r'^(?:ref|copy)\s+','',value.strip(),flags=re.I).lower()

def compatible_conditions(conditions):
    """Reject provable selector contradictions; do not guess unknown expressions."""
    known={}
    for condition in conditions:
        match=re.fullmatch(r'\$(\w+)\s*==\s*(-?\d+(?:\.\d+)?)',condition.strip())
        if not match:continue
        key,value=match[1].lower(),float(match[2])
        if key in known and known[key]!=value:return False
        known[key]=value
    return not any(evaluate_condition(c,known) is False for c in conditions)

def command_sections(path):
    result={};current=None;label=''
    for raw in Path(path).read_bytes().decode('utf-8-sig',errors='replace').splitlines():
        line=raw.strip()
        if line.startswith('[') and line.endswith(']'):
            current=line[1:-1].lower();result.setdefault(current,[]);label='';continue
        if not current:continue
        if re.match(r';\s*Draw\b',line,re.I) or re.fullmatch(r';\s*[^;=]+\(\d+\)\s*',line):
            label=line.lstrip('; ').strip();continue
        line=line.split(';',1)[0].strip()
        m=re.match(r'^(if|elseif|elif|else\s+if)\s+(.+)$',line,re.I)
        if m:result[current].append(('if' if m[1].lower()=='if' else 'elif',m[2],''))
        elif line.lower() in ('else','endif'):result[current].append((line.lower(),'',''))
        elif '=' in line:
            k,v=line.split('=',1);k=k.strip().lower()
            result[current].append((k,v.strip(),label if k=='drawindexed' else ''))
            if k=='drawindexed':label=''
    return result

def plan_static(root,ini):
    root,ini=Path(root),Path(ini);c=inspect_ini(root,ini);resources=c['resources'];sections=c['sections']
    if not c['valid']:raise ValueError('配置无法安全读取：'+str(c['errors']))
    commands=command_sections(ini);labels=draw_metadata(ini)
    from wwmi_runtime_bindings import wwmi_position_bases
    runtime_positions=wwmi_position_bases(commands,resources,sections) if c['game']=='WW' else {}
    bound={reference(v) for rows in sections.values() for k,v in rows if k=='vb0'}
    positions=[r for r in resources.values() if ('position' in r['name'].lower() or r['name'].lower() in bound) and int(r.get('stride',0)) in (12,40,56)]
    def unique(values):
        byfile={(r['file'],r.get('stride'),r.get('format')):r for r in values}
        return next(iter(byfile.values())) if len(byfile)==1 else None
    fallback={}
    for slot in SLOTS:
        values=[resources[reference(v)] for rows in sections.values() for k,v in rows if k==slot and reference(v) in resources]
        value=unique(values)
        if value:fallback[slot]=value
    if 'vb0' not in fallback:
        value=unique(positions)
        if value:fallback['vb0']=value
    if 'ib' not in fallback:
        value=unique([r for r in resources.values() if r.get('format') in ('R16_UINT','R32_UINT')])
        if value:fallback['ib']=value
    # Legacy GIMI has a parent hash with auto draw and separate index-part overrides.
    def reachable(name,seen=None):
        seen=set() if seen is None else seen
        if name in seen:return []
        seen.add(name);nodes=list(commands.get(name,[]))
        for k,v,l in list(nodes):
            if k=='run':nodes.extend(reachable(v.lower(),seen))
        return nodes
    controllers={name.lower() for name,rows in sections.items() if name.lower().startswith('textureoverride') and any(k=='drawindexed' and v.lower()=='auto' for k,v,l in reachable(name.lower())) and not any(k=='ib' for k,v,l in reachable(name.lower()))}
    auto_hashes={dict(sections[next(s for s in sections if s.lower()==name)]).get('hash') for name in controllers}
    deferred_auto=set(controllers)
    for name in controllers:
        deferred_auto.update(v.lower() for k,v,l in reachable(name) if k=='run')
    def auto_paths(name,conditions=(),stack=()):
        if name in stack:raise ValueError('配置存在循环命令引用：'+name)
        frames=[];paths=[]
        for k,v,l in commands.get(name,[]):
            if k=='if':frames.append({'previous':[v],'conditions':[v]})
            elif k in ('elif','else') and frames:
                frame=frames[-1];cs=['not ('+' || '.join(frame['previous'])+')']
                if k=='elif':cs.append(v);frame['previous'].append(v)
                frame['conditions']=cs
            elif k=='endif' and frames:frames.pop()
            current=list(conditions)+[c for frame in frames for c in frame['conditions']]
            if k=='drawindexed' and v.lower()=='auto':paths.append(current)
            elif k=='run':paths.extend(auto_paths(v.lower(),current,stack+(name,)))
        return paths
    inherited_paths={}
    for name in controllers:
        hash_value=dict(sections[next(s for s in sections if s.lower()==name)]).get('hash')
        inherited_paths.setdefault(hash_value,[]).extend(auto_paths(name))
    auto_parts=set();part_paths={}
    for name,rows in sections.items():
        values=dict(rows)
        nodes=reachable(name.lower())
        if name.lower() not in controllers and values.get('hash') and values.get('hash') in auto_hashes and any(k=='ib' for k,v,l in nodes):
            # A child may draw explicitly in one state and inherit the parent in
            # another. Keep inheritance conditional and skip already drawn states.
            part_paths[name.lower()]=inherited_paths[values['hash']]+auto_paths(name.lower())
            commands[name.lower()].append(('inherited_auto','auto',''));auto_parts.add(name.lower())
    values={'draw_type':1,'mod_enabled':1,'active':1}
    text=ini.read_bytes().decode('utf-8-sig',errors='replace')
    values.update({k.lower():float(v) for k,v in re.findall(r'(?m)^\s*global\s+(?:persist\s+)?\$(\w+)\s*=\s*(-?\d+(?:\.\d+)?)\s*(?:;.*)?$',text)})
    values.update(draw_type=1,mod_enabled=1,active=1)
    # Resolve only source-declared static Present assignments. Unknown paths or
    # unsupported expressions invalidate their target instead of keeping a stale default.
    def derive_defaults(name,stack=()):
        if name in stack:raise ValueError('配置存在循环命令引用：'+name)
        frames=[]
        for key,value,label in commands.get(name,[]):
            if key=='if':
                selected=evaluate_condition(value,values)
                frames.append({'previous':[selected],'active':selected});continue
            if key in ('elif','else') and frames:
                frame=frames[-1]
                prior=True if True in frame['previous'] else None if None in frame['previous'] else False
                candidate=evaluate_condition(value,values) if key=='elif' else True
                frame['active']=False if prior is True or candidate is False else None if prior is None or candidate is None else True
                if key=='elif':frame['previous'].append(candidate)
                continue
            if key=='endif':
                if frames:frames.pop()
                continue
            active=[f['active'] for f in frames]
            if False in active:continue
            if key.startswith('$'):
                target=key[1:].lower()
                derived=evaluate_static_value(value,values)
                if None in active or derived is None:values.pop(target,None)
                else:values[target]=derived
            elif key=='run':
                if None in active:
                    for k,v,l in reachable(value.lower()):
                        if k.startswith('$'):values.pop(k[1:].lower(),None)
                else:derive_defaults(value.lower(),stack+(name,))
    derive_defaults('present')
    values.update(draw_type=1,mod_enabled=1,active=1)
    plans=[];seen=set()
    def matching_group(state,explicit):
        ib=state.get('ib')
        if not ib:return
        name=ib['name'].lower()
        suffix_match=re.search(r'ib(\.\d+)$',name);suffix=suffix_match[1] if suffix_match else ''
        candidates=[p for p in positions if 'position' in p['name'].lower() and name.startswith(p['name'].lower().split('position')[0])]
        if suffix:candidates=[p for p in candidates if p['name'].lower().endswith('position'+suffix)]
        if not candidates:return
        size=max(len(p['name'].lower().split('position')[0]) for p in candidates)
        candidates=[p for p in candidates if len(p['name'].lower().split('position')[0])==size]
        # Runtime shape alternatives remain distinct. Only explicit vb0 base references are evidence.
        base=[p for p in candidates if p['name'].lower() in bound]
        position=unique(base or candidates)
        if not position:return
        prefix=position['name'].lower().split('position')[0]
        for slot,kind in (('vb0','position'),('vb1','texcoord'),('vb2','blend')):
            if slot in explicit:continue
            match=position if slot=='vb0' else unique([r for r in resources.values() if r['name'].lower() in (prefix+kind+suffix,prefix+kind+'cs'+suffix)])
            if match:state[slot]=match
            elif slot in state and not state[slot]['name'].lower().startswith(prefix):state.pop(slot)
    def draw(section,value,label,state,explicit,conditions,unresolved):
        if not compatible_conditions(conditions):return
        state=dict(state);matching_group(state,explicit)
        if value.lower()=='auto' and section in deferred_auto and 'ib' not in explicit and auto_parts:return
        if value.lower()=='auto' and ('ib' not in state or 'vb0' not in state):
            rows=sections.get(next((s for s in sections if s.lower()==section),''),[])
            if dict(rows).get('hash') in auto_hashes and auto_parts:return
        if 'vb0' not in state or 'ib' not in state:raise ValueError('无法确定绘制绑定的顶点或索引资源：'+section)
        if state['vb0'] not in positions:raise ValueError('尚未支持该顶点布局：'+state['vb0']['name'])
        if value.lower()=='auto':
            ib=state['ib'];size=2 if ib.get('format')=='R16_UINT' else 4 if ib.get('format')=='R32_UINT' else 0
            if not size:raise ValueError('未知索引格式：'+ib['name'])
            n=(root/ib['file']).stat().st_size
            if n%size or n//size%3:raise ValueError('自动绘制不是完整三角索引：'+ib['file'])
            count,start,base=n//size,0,0
        else:
            m=re.fullmatch(r'(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)',value)
            if not m:raise ValueError('暂不支持动态绘制表达式：'+section+' / '+value)
            count,start,base=map(int,m.groups())
        if not count:return
        meta=dict(labels.get((section,count,start,base),{}))
        if meta.get('ambiguous'):meta={}
        if label:meta['label']=label
        meta['conditions']=list(conditions)
        ident=(tuple(sorted((k,r['file']) for k,r in state.items())),count,start,base,tuple(conditions),meta.get('label',''),
            json.dumps({k:v for k,v in unresolved.items() if k!='__indexed_drawn'},sort_keys=True))
        if ident in seen:return
        seen.add(ident)
        evaluated=[evaluate_condition(x,values) for x in conditions]
        display='hidden' if False in evaluated else 'unresolved' if None in evaluated else 'visible'
        plans.append({'section':next((s for s in sections if s.lower()==section),section),'count':count,'start':start,'base':base,'bindings':state,
            'game':c['game'],'unresolved_runtime_attributes':{k:v for k,v in unresolved.items() if k!='__indexed_drawn'},'metadata_exact':True,
            'visible_by_default':display=='visible','default_display_status':display,'default_controls':dict(values),
            **meta})
        if '__runtime_position' in unresolved:plans[-1]['runtime_position']=unresolved['__runtime_position']
    def execute(section,nodes,states,stack):
        i=0
        while i<len(nodes):
            key,value,label=nodes[i]
            if key=='if':
                depth=1;j=i+1;branches=[];begin=j;previous=[value];branch_conditions=[value]
                while j<len(nodes):
                    k,v,l=nodes[j]
                    if k=='if':depth+=1
                    elif k=='endif':
                        depth-=1
                        if depth==0:
                            branches.append((branch_conditions,nodes[begin:j]));break
                    elif depth==1 and k in ('elif','else'):
                        branches.append((branch_conditions,nodes[begin:j]));begin=j+1
                        branch_conditions=['not ('+' || '.join(previous)+')']
                        if k=='elif':branch_conditions.append(v);previous.append(v)
                    j+=1
                if depth:raise ValueError('配置条件未闭合：'+section)
                if nodes[begin-1][0]!='else':branches.append((['not ('+' || '.join(previous)+')'],[]))
                following=[]
                for state,explicit,conditions,unresolved in states:
                    local=[]
                    for cs,body in branches:
                        local.extend(execute(section,body,[(dict(state),set(explicit),conditions+cs,dict(unresolved))],stack))
                    identities={json.dumps([r[0],sorted(r[1]),r[3]],sort_keys=True) for r in local}
                    if len(identities)==1:
                        sample=local[0];following.append((sample[0],sample[1],conditions,sample[3]))
                    else:following.extend(local)
                # Branches with identical bindings rejoin after endif. Earlier draws retain their conditions.
                grouped={}
                # Only an exhaustive set of branches with the same resulting
                # binding may discard its predicates altogether.
                for state,explicit,conditions,unresolved in following:
                    ident=json.dumps([state,sorted(explicit),unresolved],sort_keys=True)
                    if ident in grouped:
                        old=grouped[ident]
                        common=[]
                        for a,b in zip(old[2],conditions):
                            if a!=b:break
                            common.append(a)
                        left=' && '.join('('+c+')' for c in old[2][len(common):]) or '1'
                        right=' && '.join('('+c+')' for c in conditions[len(common):]) or '1'
                        grouped[ident]=(state,explicit,common+['('+left+') || ('+right+')'],unresolved)
                    else:grouped[ident]=(state,explicit,conditions,unresolved)
                states=list(grouped.values());i=j+1;continue
            next_states=[]
            for state,explicit,conditions,unresolved in states:
                state=dict(state);explicit=set(explicit);unresolved=dict(unresolved)
                if key in SLOTS:
                    explicit.add(key);ref=reference(value)
                    if ref in resources:
                        state[key]=resources[ref];unresolved.pop(key,None)
                        if key=='vb0':unresolved.pop('__runtime_position',None)
                    elif key=='vb0' and ref in runtime_positions:
                        proof=runtime_positions[ref];state[key]=resources[proof['source_resource']]
                        unresolved.pop(key,None);unresolved['__runtime_position']=proof
                    else:
                        state.pop(key,None)
                        if key=='vb0':unresolved.pop('__runtime_position',None)
                        if ref!='null':unresolved[key]=value
                if key=='run':
                    target=value.lower()
                    if target in stack:raise ValueError('配置存在循环命令引用：'+target)
                    if target in commands:
                        # A transparency shader's auto redraw reuses a game draw range; it adds no recoverable geometry.
                        if target.startswith('customshader') and all(k!='drawindexed' or v.lower()=='auto' for k,v,l in commands[target]):
                            next_states.append((state,explicit,conditions,unresolved));continue
                        next_states.extend(execute(target,commands[target],[(state,explicit,conditions,unresolved)],stack|{target}));continue
                    elif '\\' not in value and not target.startswith('builtin'):raise ValueError('缺少命令配置：'+value)
                if key=='drawindexed':
                    draw(section,value,label,state,explicit,conditions,unresolved)
                    unresolved['__indexed_drawn']=True
                elif key=='inherited_auto' and not unresolved.get('__indexed_drawn') and 'ib' in state:
                    for cs in part_paths.get(section,[]):
                        combined=list(conditions)+[c for c in cs if c not in conditions]
                        draw(section,'auto',label,state,explicit,combined,unresolved)
                next_states.append((state,explicit,conditions,unresolved))
            states=next_states;i+=1
        return states
    roots=[name for name in commands if name.startswith('textureoverride') and any(k in ('drawindexed','run','inherited_auto') for k,v,l in commands[name])]
    if not roots:roots=[name for name in commands if any(k=='drawindexed' for k,v,l in commands[name])]
    for name in roots:execute(name,commands[name],[(dict(fallback),set(),[],{})],{name})
    if not plans:raise ValueError('未找到支持的静态索引绘制')
    return plans
