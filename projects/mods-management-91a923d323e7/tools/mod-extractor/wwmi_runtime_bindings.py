"""Trace a known WWMI compute output to its file-backed *base* mesh only.

This does not evaluate shaders, restore shape values, or claim runtime equivalence.
The recognized producer matches WWMI ShapeKeyApplier (t6 base + u6 output).
"""
import re


def wwmi_position_bases(commands,resources,sections):
    declared={k.casefold():dict(v) for k,v in sections.items()}
    writes={};output_writers={};overwritten_outputs=set()
    ref=lambda v:re.sub(r'^(?:ref|copy)\s+','',v.strip(),flags=re.I).casefold()
    for name,nodes in commands.items():
        conditional=any(k in ('if','elif','else','endif') for k,_,_ in nodes)
        bound={};produced={}
        for key,value,_ in nodes:
            if key in ('cs-t6','cs-u6'):bound[key]=ref(value)
            if key=='run':
                produced.clear()
                source_name=None
                if value.casefold()=='customshader\\wwmiv1\\shapekeyapplier' and not conditional:
                    source=resources.get(bound.get('cs-t6'));target=declared.get(bound.get('cs-u6'),{})
                    if (source and int(source.get('stride',0))==12 and
                        source.get('format')=='R32G32B32_FLOAT' and target.get('type','').casefold()=='rwbuffer' and
                        int(target.get('stride',0))==12 and target.get('format','').upper().removeprefix('DXGI_FORMAT_')=='R32_FLOAT'):
                        source_name=source['name'].casefold();produced[bound['cs-u6']]=source_name
                if bound.get('cs-u6') in declared:
                    output_writers.setdefault(bound['cs-u6'],set()).add(source_name)
            if key.startswith('resource') and key in declared:
                produced.pop(key,None)
                if declared[key].get('type','').casefold()=='rwbuffer':overwritten_outputs.add(key)
                base=produced.get(ref(value)) if re.match(r'^(?:ref|copy)\s+',value,re.I) and not conditional else None
                proof=None
                if base:
                    proof={'status':'source_base_only','runtime_resource':key,'source_resource':base,
                        'producer':name,'kernel':'CustomShader\\WWMIv1\\ShapeKeyApplier',
                        'runtime_output':ref(value),'runtime_deformation_status':'unverified',
                        'scope':'file-backed base positions only; runtime shape offsets not applied'}
                writes.setdefault(key,[]).append(proof)
    result={}
    for alias,proofs in writes.items():
        if (all(p is not None for p in proofs) and len({p['source_resource'] for p in proofs})==1 and
            all(p['runtime_output'] not in overwritten_outputs and
                output_writers.get(p['runtime_output'])=={p['source_resource']} for p in proofs)):
            result[alias]=proofs[0]
    return result
