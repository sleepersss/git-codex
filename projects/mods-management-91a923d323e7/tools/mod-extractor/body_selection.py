"""Source-labelled skin selection, independent of character names."""
import re,ast

ZERO_CONTROLS={'dress','cloth','clothing','coat','glove','pants','bra','footshoes','stocking','stockinglength',
    'headdress','necklace','belt','bow','leglace','bracelet','shawl','armlet','tamagotchi','state','state2','xray',
    'rub','lick','buttmark','wombtattoo','trans','sleeve','ring','virginblood'}

def source_state_hint(name):
    """Only explicit four-control exporter subfolder names establish a bare source state."""
    text=name.casefold()
    controls=('cloth','glove','shoes','bra')
    return {k:0 for k in controls} if all(re.search(r'\bno[_ -]?'+k+r'\b',text) for k in controls) else {}

def variant_conditions(conditions):
    # The static full model has already been verified. This WWMI wrapper tests
    # the live game's merged skeleton, not a clothes/body switch.
    return [c for c in conditions if not re.fullmatch(r'ResourceMergedSkeleton\s*!==\s*null',c,re.I)
            and '->' not in c]

def evaluate_static_value(expression,values):
    """Interpret a restricted arithmetic/boolean tree; unknown variables are never zero-filled."""
    expression=re.sub(r'\$(\w+)',lambda m:m[1].casefold(),expression)
    expression=expression.replace('&&',' and ').replace('||',' or ')
    expression=re.sub(r'!(?!=)',' not ',expression).strip()
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float,bool):return node.value
        if isinstance(node,ast.Name):return values[node.id.casefold()]
        if isinstance(node,ast.BoolOp):
            unknown=False;is_and=isinstance(node.op,ast.And)
            for child in node.values:
                try:value=bool(visit(child))
                except (ValueError,KeyError):unknown=True;continue
                if is_and and not value:return False
                if not is_and and value:return True
            if unknown:raise KeyError('unknown boolean operand')
            return is_and
        if isinstance(node,ast.UnaryOp):
            value=visit(node.operand)
            if isinstance(node.op,ast.Not):return not value
            if isinstance(node.op,ast.USub):return -value
            if isinstance(node.op,ast.UAdd):return value
        if isinstance(node,ast.BinOp):
            left=visit(node.left);right=visit(node.right)
            if isinstance(node.op,ast.Add):return left+right
            if isinstance(node.op,ast.Sub):return left-right
            if isinstance(node.op,ast.Mult):return left*right
            if isinstance(node.op,ast.Div):return left/right
            if isinstance(node.op,ast.Mod):return left%right
        if isinstance(node,ast.Compare):
            left=visit(node.left)
            for op,right in zip(node.ops,node.comparators):
                right=visit(right)
                predicates={ast.Eq:lambda:left==right,ast.NotEq:lambda:left!=right,ast.Lt:lambda:left<right,
                    ast.LtE:lambda:left<=right,ast.Gt:lambda:left>right,ast.GtE:lambda:left>=right}
                if type(op) not in predicates:raise ValueError('unsupported comparison')
                if not predicates[type(op)]():return False
                left=right
            return True
        raise ValueError('unsupported condition')
    try:return visit(ast.parse(expression,mode='eval').body)
    except (ValueError,KeyError,SyntaxError,ZeroDivisionError):return None

def evaluate_condition(expression,values):
    result=evaluate_static_value(expression,values)
    return None if result is None else bool(result)

def classify_label(label):
    text=label.casefold()
    negated=r'(丝袜|内裤|衣服)(无|なし)|no[_ -]?(?:stockings?|panties)'
    positive=re.sub(negated,'',text)
    if re.search(r'stocking|socks|glove|shoe|boot|heel|dress|sleeve|leotard|corset|underwear|panties|bra\b|collar|ring|rope|toy|patch|bandage|ornament|skirt|丝袜|袜|鞋|靴|脖环|裙|手套|内裤|饰品|项圈|自慰器|腿环',positive):return 'clothes'
    if re.search(negated+r'|bare|nude|裸体|裸身',text):return 'skin'
    if re.search(r'\bbody(?:\b|_|up\b|down\b)|\bskin\b|\b(nipples?|neck|hands?|feet|legs?|arms?)\b|身体|上半身|下半身|下身|手臂|(?:^|[.\s])手\d*(?:$|[\s(])|脖子|乳突|腿|脚|裸',text):return 'skin'
    return 'unknown'

def select_parts(rows):
    from body_candidates import select_body_candidates
    return select_body_candidates(rows)['selected']

def body_draw_metadata(draw,legacy,neutral,source_hint):
    """Use actual per-occurrence conditions when a range has several variants."""
    exact=draw.get('metadata_exact',False)
    label=draw.get('label','') if exact else legacy.get('label',draw.get('label',''))
    # Re-establish every inferred annotation from the current source evidence;
    # an old label alone cannot establish a clothing-off state.
    label=re.sub(r'\s*\[source (?:nude toggle state|clothing-off body|four clothing-off controls body)\]','',label)
    conditions=draw.get('conditions',[]) if exact else legacy.get('conditions',draw.get('conditions',[]))
    is_neutral=bool(neutral) and all(evaluate_condition(c,neutral) is True for c in variant_conditions(conditions)) if exact else legacy.get('neutral_body_state',False)
    controls={}
    if classify_label(label)=='unknown':
        if source_hint:label+=' [source four clothing-off controls body]'
        elif is_neutral:label+=' [source nude toggle state]'
        elif legacy.get('clothing_off_controls'):
            label+=' [source clothing-off body]';controls=legacy['clothing_off_controls']
    return {'label':label,'conditions':conditions,'neutral_body_state':bool(source_hint) or is_neutral,
            'neutral_controls':source_hint or (neutral if is_neutral else controls)}

def draw_metadata(path,include_neutral_state=False):
    text=path.read_bytes().decode('utf-8-sig',errors='replace');section='';label='';frames=[];rows={};nude_vars={};assignments=[]
    def conditions():return [c for f in frames for c in f['current']]
    for raw in text.splitlines():
        line=raw.strip()
        if line.startswith('[') and line.endswith(']'):section=line[1:-1];label='';frames=[]
        elif re.match(r';\s*Draw\b',line,re.I) or re.fullmatch(r';\s*[^;=]+\(\d+\)\s*',line):label=line.lstrip('; ').strip()
        elif line.startswith('if '):frames.append({'previous':[line[3:].strip()],'current':[line[3:].strip()]})
        elif line.startswith(('elseif ','elif ','else if ')):
            if frames:
                f=frames[-1];expression=re.sub(r'^(?:elseif|elif|else\s+if)\s+','',line).strip()
                f['current']=['not ('+' || '.join(f['previous'])+')',expression];f['previous'].append(expression)
        elif line=='else':
            if frames:frames[-1]['current']=['not ('+' || '.join(frames[-1]['previous'])+')']
        elif line=='endif':
            if frames:frames.pop()
        elif re.match(r'\$\w+\s*=',line):
            name,rhs=line.split('=',1);name=name.strip()[1:].casefold();rhs=rhs.strip()
            if section.casefold()!='constants' and not section.casefold().startswith('key'):
                assignments.append((section.casefold(),name,rhs,conditions()))
            # An assignment is evidence only inside the actual positive clothes-off branch.
            cs=conditions()
            if name.startswith('base') and rhs=='1' and any(re.fullmatch(r'\$(?:dress\w*|clothes\w*|clothing\w*)\s*==\s*0',c,re.I) for c in cs) and not any(c.startswith('not (') for c in cs):
                controls={m[1].casefold():0 for c in cs if (m:=re.fullmatch(r'\$(dress\w*|clothes\w*|clothing\w*)\s*==\s*0',c,re.I))}
                nude_vars.setdefault(name,set()).add(tuple(sorted(controls.items())))
        elif line.startswith('drawindexed'):
            m=re.search(r'=\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)',line)
            if m:
                key=(section.lower(),int(m[1]),int(m[2]),int(m[3]));row={'label':label,'conditions':conditions()}
                if key in rows and rows[key]!=row:rows[key]={'label':'','conditions':[],'ambiguous':True}
                else:rows.setdefault(key,row)
            label=''
    # Source explicitly declares which base is active with clothing turned off.
    for row in rows.values():
        if not row.get('ambiguous') and classify_label(row['label'])=='unknown':
            states={state for v,options in nude_vars.items() for state in options if any(
                re.fullmatch(r'\$'+re.escape(v)+r'\s*==\s*1',c,re.I) for c in row['conditions'])}
            if len(states)==1:
                row['label']+=' [source clothing-off body]';row['clothing_off_controls']=dict(next(iter(states)))
    constants={name.casefold():float(value) for name,value in re.findall(r'(?m)^\s*global\s+(?:persist\s+)?\$(\w+)\s*=\s*(-?\d+(?:\.\d+)?)\s*$',text)}
    clothing={name for name in constants if name in {'dress','cloth','clothing','coat','glove','pants','bra','footshoes','stocking','stockinglength'}}
    # Toggle-driven packs may provide no draw labels. Use their actual clothes-off state.
    # Require independent clothing controls; a lone ambiguous switch is insufficient.
    neutral=None
    if len(clothing)>=4 and {'dress','bra','pants'}<=clothing:
        neutral={name:(0 if name in ZERO_CONTROLS else value) for name,value in constants.items()}
        for source,name,rhs,cs in assignments:
            if name in ZERO_CONTROLS:continue  # these controls define the chosen static neutral state
            if source!='present':neutral.pop(name,None);continue
            active=[evaluate_condition(c,neutral) for c in cs]
            if any(v is False for v in active):continue
            if any(v is None for v in active) or not re.fullmatch(r'-?\d+(?:\.\d+)?',rhs):neutral.pop(name,None)
            else:neutral[name]=float(rhs)
        for key,row in rows.items():
            # A called command list can have additional caller conditions; do not infer those.
            row['neutral_body_state']=not row.get('ambiguous') and key[0].startswith('textureoverride') and all(evaluate_condition(c,neutral) is True for c in variant_conditions(row['conditions']))
            if row['neutral_body_state'] and classify_label(row['label'])=='unknown':
                row['label']+=' [source nude toggle state]'
                row['neutral_controls']={name:neutral[name] for name in clothing}
    return (rows,neutral) if include_neutral_state else rows
