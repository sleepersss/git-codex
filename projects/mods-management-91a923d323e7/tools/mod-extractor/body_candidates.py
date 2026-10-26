"""Bounded source-state comparison; labels propose candidates, never prove anatomy."""
import itertools,re,math
from body_selection import classify_label,variant_conditions,evaluate_condition,ZERO_CONTROLS

CLOTHING_OFF=ZERO_CONTROLS|{'yifu','bishi','xiezi','waitao','jinshenyi','siwa','wenshen','xz','boshi','yangju','gangzhu'}

INFERRED=re.compile(r'\s*\[source (?:nude toggle state|four clothing-off controls body|clothing-off body)\]')


def explicit_skin(row):
    return classify_label(INFERRED.sub('',row.get('label','')))=='skin'


def retain_skin_component(row,connected):
    """An explicit skin part is not an accessory merely because it is disconnected."""
    return bool(connected) or explicit_skin(row)


def regions(label):
    text=label.casefold();result=set()
    for region,pattern in (
        ('body',r'\bbody(?:\b|_)|身体(?!手臂)|裸身|裸体'),
        ('upper',r'bodyup|上半身'),('lower',r'bodydown|下半身|下身'),
        ('arms',r'\barms?\b|手臂'),('hands',r'\bhands?\b|(?:^|[.\s])手\d*(?:$|[\s(])'),
        ('legs',r'\blegs?\b|腿'),('feet',r'\b(?:feet|foot)\b|裸足|脚'),
        ('neck',r'\bneck\b|脖子')):
        if re.search(pattern,text):result.add(region)
    return result


def select_body_candidates(rows,program=None,max_states=4096):
    result={'status':'unresolved','selected':[],'controls':{},'resolved_controls':{},
        'alternatives':[],'excluded':[],'unresolved':[],'states_evaluated':0,
        'search_limit':max_states,'scope':'source-label candidates; anatomy and runtime not verified',
        'static_geometry_guards':['ResourceMergedSkeleton !== null','$mod_enabled']}
    skin=[]
    for row in rows:
        kind=classify_label(row.get('label',''))
        if kind!='skin':result['excluded'].append({'name':row['name'],'reason':kind});continue
        skin.append(row)
    if not skin:return result
    conditions={r['name']:variant_conditions(r.get('conditions',[])) for r in skin}
    for row in skin:
        if not explicit_skin(row):
            conditions[row['name']]+=['$'+k+' == '+str(v) for k,v in row.get('neutral_controls',{}).items()]
    # The full-model source data was already checked. This readiness flag is
    # ignored only for static geometry selection, never asserted true in game.
    conditions={n:[c for c in cs if not re.fullmatch(r'\s*\$mod_enabled\s*',c,re.I)] for n,cs in conditions.items()}
    variables={v.casefold() for cs in conditions.values() for c in cs for v in re.findall(r'\$(\w+)',c)}
    if program is not None:domains=program.domains_for(variables)
    else:
        # Standalone diagnostics accept only finite selectors explicitly compared
        # with source literals. Bare runtime booleans have no inferred domain.
        domains={}
        for cs in conditions.values():
            for c in cs:
                for name,value in re.findall(r'\$(\w+)\s*(?:==|!=)\s*(-?\d+(?:\.\d+)?)',c):
                    domains.setdefault(name.casefold(),{0,1}).add(float(value))
        domains={k:sorted(v) for k,v in sorted(domains.items())}
    result['state_space']=math.prod(len(v) for v in domains.values())
    if result['state_space']>max_states:
        result['status']='search_limited';return result
    variants={};unknown=set()
    for combination in itertools.product(*domains.values()):
        controls=dict(zip(domains,combination))
        values=program.resolve(controls) if program is not None else controls
        selected=[]
        for row in skin:
            outcomes=[evaluate_condition(c,values) for c in conditions[row['name']]]
            if False in outcomes:continue
            if None in outcomes:unknown.add(row['name']);continue
            selected.append(row)
        result['states_evaluated']+=1
        names=tuple(sorted(r['name'] for r in selected))
        if not names:continue
        if names not in variants:
            variants[names]={'names':list(names),'controls':controls,'resolved_controls':values,
                'regions':sorted(set().union(*(regions(r.get('label','')) for r in selected)))}
        if len(variants)>256:
            result['status']='search_limited';return result
    alternatives=list(variants.values())
    # Prefer only a strict superset of source-labelled complementary regions.
    # Equal or incomparable variants are retained for review, independent of order.
    best=[a for a in alternatives if not any(set(a['regions'])<set(b['regions']) for b in alternatives)]
    result['alternatives']=sorted(best,key=lambda r:r['names'])
    result['unresolved']=sorted(unknown)
    if unknown:return result
    if len(best)>1:
        scores=[]
        for option in best:
            controls=option.get('resolved_controls') or option.get('controls') or {}
            scores.append(sum(1 for key,value in controls.items() if key in CLOTHING_OFF and value))
        lowest=min(scores) if scores else None
        narrowed=[option for option,score in zip(best,scores) if score==lowest]
        if len(narrowed)==1:best=narrowed
        else:
            result['status']='ambiguous';result['alternatives']=sorted(best,key=lambda r:r['names']);return result
    if len(best)!=1:
        result['status']='ambiguous' if best else 'unresolved';return result
    chosen=best[0]
    unconditional_ex=[r for r in skin if r['name'] in chosen['names'] and
        re.search(r'\bbody_ex\d+\b',r.get('label',''),re.I) and not conditions[r['name']]]
    if unconditional_ex and len([r for r in skin if r['name'] in chosen['names'] and 'body' in regions(r.get('label',''))])>1:
        result['status']='ambiguous';result['ambiguity_reason']='unconditional_body_variants';return result
    result.update(status='selected',selected=chosen['names'],controls=chosen['controls'],resolved_controls=chosen['resolved_controls'])
    for row in skin:
        if row['name'] not in result['selected']:
            result['excluded'].append({'name':row['name'],'reason':'different_source_state'})
    return result
