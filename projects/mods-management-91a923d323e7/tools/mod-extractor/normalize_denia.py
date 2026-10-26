from pathlib import Path
import re,json,sys
run=Path(sys.argv[1]).resolve()
job=json.loads((run/'job.json').read_text(encoding='utf-8'))
ini=Path(job['main_ini']);text=ini.read_text(encoding='utf-8-sig')
sections={m[1]:m[2] for m in re.finditer(r'^\[([^]]+)\]\s*\n(.*?)(?=^\[|\Z)',text,re.M|re.S)}
for group in ('ib0','ib1','ib2'):
    parts=['[Constants]\nglobal $mesh_vertex_count = '+re.search(r'global \$mesh_vertex_count_'+group+r' = (\d+)',text)[1],
           '[CommandListOverrideSharedResources]\nib = ResourceIndexBuffer\nvb0 = ResourcePositionBuffer\nvb1 = ResourceVectorBuffer\nvb2 = ResourceTexCoordBuffer\nvb3 = ResourceColorBuffer\nvb4 = ResourceBlendBuffer']
    maps={}
    for section,body in sections.items():
        match=re.fullmatch(r'CommandListDraw(?:Geometry)?Component(\d+)_'+group,section)
        if not match:continue
        draws=[];label=''
        for line in body.splitlines():
            if line.strip().startswith('; Draw'):label=line.strip()[2:]
            m=re.match(r'\s*drawindexed\s*=\s*(\d+),\s*(\d+),\s*0',line)
            if m:draws.append({'count':int(m[1]),'start':int(m[2]),'label':label})
        if draws:
            c=match[1];maps[c]=draws
            parts.append('[TextureOverrideComponent'+c+']\nhash = 00000000\nmatch_first_index = '+str(draws[0]['start'])+'\nrun = CommandListOverrideSharedResources\n'+ '\n'.join('drawindexed = {count}, {start}, 0'.format(**d) for d in draws))
    for name in ('Index','Position','Blend','Vector','Color','TexCoord','ShapeKeyOffset','ShapeKeyVertexId','ShapeKeyVertexOffset'):
        resource='Resource'+name+'Buffer_'+group
        if resource in sections:
            body=re.sub(r'(?m)^filename\s*=\s*(.+)$',lambda m:'filename = ../'+ini.parent.name+'/'+m[1].strip(),sections[resource])
            parts.append('[Resource'+name+'Buffer]\n'+body)
    folder=run/'input'/('normalized-'+group);folder.mkdir(exist_ok=True)
    target=folder/'mod.ini';target.write_text('\n\n'.join(parts),encoding='utf-8')
    (run/(group+'-draw-map.json')).write_text(json.dumps(maps,ensure_ascii=False,indent=2),encoding='utf-8')
print('Created three isolated canonical INIs; original unchanged')
