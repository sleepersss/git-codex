"""Independent saved-file checks against source buffers and emitted shape streams."""
import bpy,numpy as np,sys,json,re
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve();job=json.loads((run/'job.json').read_text(encoding='utf-8'))
source=Path(job['main_ini']).parent;results={};cache={}
def buffers(group,variant):
    key=(group,variant)
    if key in cache:return cache[key]
    p=source/'Meshes';prefix=group+'_' if group else ''
    pos=np.fromfile(p/(prefix+'Position.buf'),dtype='<f4').reshape(-1,3)
    tex=np.fromfile(p/(prefix+'TexCoord.buf'),dtype='<f2').reshape(-1,8).astype('f4')
    b=np.fromfile(p/(prefix+('Blend_c5remap.buf' if variant else 'Blend.buf')),dtype='u1').reshape(len(pos),-1)
    color=np.fromfile(p/(prefix+'Color.buf'),dtype='u1').reshape(-1,4)
    ib=np.fromfile(p/(prefix+'Index.buf'),dtype='<u4')
    external={}
    if job['name']=='denia' and group in ('ib0','ib2'):
        offsets=np.fromfile(p/(prefix+'ExternalShapeKeyVertexOffset.buf'),dtype='<u4')
        channels=np.fromfile(p/(prefix+'ExternalShapeKeyRecordChannel.buf'),dtype='<u4')
        deltas=np.fromfile(p/(prefix+'ExternalShapeKeyRecordDelta.buf'),dtype='<f4').reshape(-1,3)
        vertices=np.repeat(np.arange(len(pos)),np.diff(offsets))
        channel_keys={int(x)-100:int(k) for x,k in re.findall(r'post x(\d+) = \$ShapeKey_(\d+)',Path(job['main_ini']).read_text(encoding='utf-8-sig'))}
        for c in np.unique(channels):
            delta=np.zeros_like(pos);mask=channels==c;np.add.at(delta,vertices[mask],deltas[mask])
            external['External ShapeKey_'+str(channel_keys[int(c)])]=delta
    cache[key]=(pos,tex,b,color,ib,external);return cache[key]
decision=json.loads((run/'body-decision.json').read_text(encoding='utf-8'))
if decision['status']!='eligible' and (run/'models/body.blend').exists():
    raise RuntimeError('Unexpected body output in abandoned task')
for role in (('full','body') if decision['status']=='eligible' else ('full',)):
    bpy.ops.wm.open_mainfile(filepath=str(run/'models'/f'{role}.blend'));checks=[]
    for obj in [o for o in bpy.data.objects if o.type=='MESH']:
        mesh=obj.data;n=len(mesh.vertices)
        mapping=np.empty(n,dtype=np.int32);mesh.attributes['SourceVertexIndex'].data.foreach_get('value',mapping)
        pos,tex,b,color,ib,external=buffers(obj['SourceGroup'],obj.get('BlendVariant')=='c5remap')
        actual=np.empty(n*3,dtype='f4');mesh.vertices.foreach_get('co',actual)
        assert np.array_equal(actual.reshape(-1,3),pos[mapping]),obj.name+' positions'
        loops=np.empty(len(mesh.loops),dtype=np.int32);mesh.loops.foreach_get('vertex_index',loops);source_loops=mapping[loops]
        d=json.loads(obj['SourceDraw']);original=ib[d['start']:d['start']+d['count']].reshape(-1,3)
        if role=='body':original=original[np.all(np.isin(original,mapping),axis=1)]
        assert np.array_equal(source_loops.reshape(-1,3),original),obj.name+' topology'
        uv_mapping=json.loads(obj.get('UVSourceLaneMap',json.dumps({'TEXCOORD'+(str(i) if i else '')+'.xy':i for i in range(4)})))
        expected_uv_mapping={'TEXCOORD'+(str(i) if i else '')+'.xy':i for i in range(4)
                             if np.isfinite(tex[mapping,2*i:2*i+2]).all() and not (job['name']=='iuno' and i==1)}
        assert uv_mapping==expected_uv_mapping,obj.name+' source UV lane map'
        for layer_name,i in uv_mapping.items():
            layer=mesh.uv_layers[layer_name]
            expected=tex[source_loops,2*i:2*i+2].copy();expected[:,1]=1-expected[:,1]
            uv=np.empty(len(mesh.loops)*2,dtype='f4');layer.data.foreach_get('uv',uv)
            if not np.array_equal(uv.reshape(-1,2),expected):
                mismatch=np.where(np.any(uv.reshape(-1,2)!=expected,axis=1))[0]
                print('UV_DIFFERENCE',obj.name,i,len(mismatch),uv.reshape(-1,2)[mismatch[:3]],expected[mismatch[:3]],flush=True)
            assert np.array_equal(uv.reshape(-1,2),expected),obj.name+' UV'+str(i)
        source_tex=np.fromfile(source/'Meshes'/(((obj['SourceGroup']+'_') if obj['SourceGroup'] else '')+'TexCoord.buf'),dtype='u1').reshape(-1,16)
        for lane in range(4):
            attr_name='SourceTexcoordRaw'+str(lane)
            assert attr_name in mesh.attributes,obj.name+' missing '+attr_name
            raw=np.empty(n,dtype=np.int32);mesh.attributes[attr_name].data.foreach_get('value',raw)
            assert np.array_equal(raw,source_tex[mapping,lane*4:lane*4+4].copy().view('<i4').ravel()),obj.name+' '+attr_name
        lanes=b.shape[1]//2
        for v,old in zip(mesh.vertices,mapping):
            expected={str(int(g)):float(np.float32(float(w)/255.0)) for g,w in zip(b[old,:lanes],b[old,lanes:lanes*2]) if w}
            actual={obj.vertex_groups[g.group].name:g.weight for g in v.groups}
            assert actual==expected,obj.name+' weights'
        for lane in range(b.shape[1]//4):
            raw=np.empty(n,dtype=np.int32);mesh.attributes['SourceBlendRaw'+str(lane)].data.foreach_get('value',raw)
            assert np.array_equal(raw,b[mapping,lane*4:lane*4+4].copy().view('<i4').ravel())
        colors=np.empty(len(mesh.loops)*4,dtype='f4');mesh.vertex_colors['COLOR'].data.foreach_get('color',colors)
        assert np.allclose(colors.reshape(-1,4),color[source_loops]/255.0,rtol=0,atol=1e-6),obj.name+' color'
        fmt=Path(obj['SourceFmt']);ft=fmt.read_text(encoding='utf-8-sig');stride=obj['SourceStride']
        compact=np.fromfile(fmt.with_suffix('.vb'),dtype='u1').reshape(-1,stride)
        compactib=np.fromfile(fmt.with_suffix('.ib'),dtype='<u4')
        full_original=ib[d['start']:d['start']+d['count']]
        reverse_map={int(old):int(new) for new,old in zip(compactib,full_original)}
        compact_ids=np.array([reverse_map[int(i)] for i in mapping])
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from wwmi_shapekeys import load_shapekeys
        disk_shapes=load_shapekeys(source/'Meshes',Path(job['main_ini']).read_text(encoding='utf-8-sig',errors='replace'),
                                   (obj['SourceGroup']+'_') if obj['SourceGroup'] else '')
        named={channel['name']:channel for channel in disk_shapes.get('channels',{}).values()}
        shape_count=0
        if mesh.shape_keys:
            for key in mesh.shape_keys.key_blocks:
                if key.name=='Basis':continue
                if key.name in external:target=pos[mapping]+external[key.name][mapping]
                else:
                    fmt_target=None
                    if key.name.startswith('Deform ') and 'SemanticName: SHAPEKEY' in ft.replace('\r',''):
                        try:
                            number=int(key.name.split(' ')[1])
                            block=next(s for s in re.split(r'element\[\d+\]:',ft)[1:] if 'SemanticName: SHAPEKEY\n' in s.replace('\r','') and int(re.search(r'SemanticIndex: (\d+)',s)[1])==number)
                            offset=int(re.search(r'AlignedByteOffset: (\d+)',block)[1])
                            delta=compact[compact_ids,offset:offset+6].copy().view('<f2').reshape(-1,3).astype('f4')
                            fmt_target=pos[mapping]+delta
                        except (StopIteration,ValueError,TypeError):
                            fmt_target=None
                    if fmt_target is not None:target=fmt_target
                    elif key.name in named:
                        delta=np.zeros_like(pos)
                        for vertex,offset in named[key.name]['vertices'].items():
                            if vertex<len(pos):delta[vertex]=offset
                        target=pos[mapping]+delta[mapping]
                    else:
                        raise AssertionError(obj.name+' shape '+key.name+' has no source table')
                actual=np.empty(n*3,dtype='f4');key.data.foreach_get('co',actual)
                assert np.array_equal(actual.reshape(-1,3),target),obj.name+' shape '+key.name
                assert key.value==0
                shape_count+=1
        checks.append({'name':obj.name,'vertices':n,'triangles':len(mesh.polygons),'coordinates_source_exact':True,'topology_source_exact':True,'verified_uv_layers':len(uv_mapping),'raw_texcoord_exact':all('SourceTexcoordRaw'+str(i) in mesh.attributes for i in range(4)),
                       'ambiguous_texcoord_lanes':json.loads(obj.get('AmbiguousTexcoordLanes','[]')),
                       'weights_exact':True,'raw_blend_exact':True,'color_source_verified':True,'shape_targets_verified':shape_count,'custom_normals_present':mesh.has_custom_normals})
    assert checks;results[role]={'saved_file_reopened':True,'meshes':checks}
results['status']='passed';results['limits']=['Numeric bone groups are not a skeleton','Native shape targets checked against Sword conversion, external keys against source HLSL rule','No textures, shaders or in-game animated export check']
if any(m['ambiguous_texcoord_lanes'] for role in ('full','body') if role in results for m in results[role]['meshes']):
    results['limits'].append('Non-finite half lanes are retained as exact raw attributes; their source semantics are unverified and not reported as valid UV')
(run/'data-preservation-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('DATA_PRESERVATION_VERIFIED',len(results['full']['meshes']),decision['status'])
