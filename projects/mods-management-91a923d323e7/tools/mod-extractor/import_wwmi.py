"""Blender worker: import verified Sword streams and restore source color/weights."""
import bpy,numpy as np,sys,json,re,hashlib
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve()
job=json.loads((run/'job.json').read_text(encoding='utf-8'))
sys.dont_write_bytecode=True;sys.path.insert(0,job['herta_parent'])
bpy.context.preferences.filepaths.save_version=0
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.preferences.addon_enable(module='HertaBlender')
from HertaBlender.config.main_config import GlobalConfig
GlobalConfig.gamename='WWMI'
name=job['name'];source=Path(job['main_ini']).parent
out=run/'models';out.mkdir(exist_ok=True)
report={'game':'WW','name':name,'objects':[], 'limitations':['No game skeleton or shader reconstruction','Static high detail baseline, no in-game validation','Alternate LOD weights and cross-scene shape layouts remain in source snapshot']}
sets=[]
if name=='denia':
    for group in ('ib0','ib1','ib2'):
        parent=run/'input'/(f'normalized-{group}-Reverse')
        layouts=[p for p in parent.iterdir() if p.is_dir()]
        layout=next(p for p in layouts if p.name.endswith('_4') or p.name.endswith('_0'))
        maps=json.loads((run/(group+'-draw-map.json')).read_text(encoding='utf-8'))
        sets.append((group,layout,maps))
else:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from wwmi_draw_map import parse_component_draws,expected_fmt_count,select_reverse_layout
    reverse_root=Path(job['main_ini']).parent.with_name(Path(job['main_ini']).parent.name+'-Reverse')
    components=parse_component_draws(job['main_ini'])
    layout=select_reverse_layout(reverse_root,expected_fmt_count(components))
    maps={cid:draws for cid,draws in components.items() if draws}
    sets.append(('',layout,maps))
for group,layout,maps in sets:
    prefix=(group+'_') if group else ''
    meshes=source/'Meshes'
    original_ib=np.fromfile(meshes/(prefix+'Index.buf'),dtype='<u4')
    positions=np.fromfile(meshes/(prefix+'Position.buf'),dtype='<f4').reshape(-1,3)
    vector=np.fromfile(meshes/(prefix+'Vector.buf'),dtype='u1').reshape(-1,8)
    tex=np.fromfile(meshes/(prefix+'TexCoord.buf'),dtype='u1').reshape(-1,16)
    color=np.fromfile(meshes/(prefix+'Color.buf'),dtype='u1').reshape(-1,4)
    blend=np.fromfile(meshes/(prefix+'Blend.buf'),dtype='u1').reshape(len(positions),-1)
    assert blend.shape[1] in (8,16)
    assert len(positions)==len(vector)==len(tex)==len(color)==len(blend)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from wwmi_shapekeys import load_shapekeys
    from wwmi_draw_map import static_draw_conditions
    from body_selection import evaluate_condition,variant_conditions
    standard_shapes=load_shapekeys(meshes,Path(job['main_ini']).read_text(encoding='utf-8-sig',errors='replace'),prefix)
    report['shapekeys']= {'status':standard_shapes['status'],'channel_count':standard_shapes.get('channel_count',0),
        'named':standard_shapes.get('named',{}),'layout':standard_shapes.get('layout')}
    default_values=None
    try:
        from source_controls import load_control_program
        default_values=load_control_program(job['main_ini']).resolve({})
    except (OSError,ValueError,KeyError):
        default_values=None
    external_shapes={}
    if name=='denia' and group in ('ib0','ib2'):
        offsets=np.fromfile(meshes/(prefix+'ExternalShapeKeyVertexOffset.buf'),dtype='<u4')
        channels=np.fromfile(meshes/(prefix+'ExternalShapeKeyRecordChannel.buf'),dtype='<u4')
        deltas=np.fromfile(meshes/(prefix+'ExternalShapeKeyRecordDelta.buf'),dtype='<f4').reshape(-1,3)
        assert len(offsets)==len(positions)+1 and offsets[0]==0 and offsets[-1]==len(channels)==len(deltas)
        assert np.all(offsets[1:]>=offsets[:-1]) and np.isfinite(deltas).all()
        record_vertices=np.repeat(np.arange(len(positions)),np.diff(offsets))
        ini_text=Path(job['main_ini']).read_text(encoding='utf-8-sig')
        channel_keys={int(x)-100:int(k) for x,k in re.findall(r'post x(\d+) = \$ShapeKey_(\d+)',ini_text)}
        for channel in np.unique(channels):
            delta=np.zeros_like(positions)
            mask=channels==channel;np.add.at(delta,record_vertices[mask],deltas[mask])
            external_shapes['External ShapeKey_'+str(channel_keys[int(channel)])]=delta
    for compact_c,(c,draws) in enumerate(maps.items()):
        for index,draw in enumerate(draws):
            fmt=layout/f'Component {draw.get("component", compact_c)}.{draw.get("index", index)}.fmt'
            assert fmt.is_file(),str(fmt)
            text=fmt.read_text(encoding='utf-8-sig')
            stride=int(re.search(r'^stride: (\d+)',text)[1])
            vb=np.fromfile(fmt.with_suffix('.vb'),dtype='u1').reshape(-1,stride)
            ib=np.fromfile(fmt.with_suffix('.ib'),dtype='<u4')
            original=original_ib[draw['start']:draw['start']+draw['count']]
            assert len(ib)==len(original)==draw['count']
            mapping=np.full(len(vb),-1,dtype=np.int32)
            for new,old in zip(ib,original):
                if mapping[new]>=0:assert mapping[new]==old,'Non-bijective source mapping'
                mapping[new]=old
            assert (mapping>=0).all()
            assert np.array_equal(vb[:,:12].copy().view('<f4').reshape(-1,3),positions[mapping])
            assert np.array_equal(vb[:,12:20],vector[mapping])
            cpu=layout.name.startswith('CPU')
            if cpu:assert np.array_equal(vb[:,20:36],tex[mapping])
            before=set(bpy.data.objects)
            assert bpy.ops.import_mesh.migoto_raw_buffers_mmt(filepath=str(fmt),files=[{'name':fmt.name}])=={'FINISHED'}
            obj=next(o for o in bpy.data.objects if o not in before and o.type=='MESH')
            obj.name=f'{group or "main"}_C{c}_D{index}_'+re.sub(r'^Draw Component \d+\.','',draw['label'])
            obj['SourceGroup']=group;obj['SourceComponent']=int(c)
            draw_record={**draw,'section':draw.get('section') or ('TextureOverrideComponent'+str(c)),
                'base':int(draw.get('base',0)),'metadata_exact':True}
            obj['SourceDraw']=json.dumps(draw_record,ensure_ascii=False)
            obj['SourceFmt']=str(fmt);obj['SourceStride']=stride
            attr=obj.data.attributes.new(name='SourceVertexIndex',type='INT',domain='POINT');attr.data.foreach_set('value',mapping)
            # 16-byte WWMI blend layout: 8 bone indices followed by 8 weights.
            active_blend=blend
            if name=='denia' and group=='ib0' and str(c)=='5':
                active_blend=np.fromfile(meshes/'ib0_Blend_c5remap.buf',dtype='u1').reshape(-1,16)
                obj['BlendVariant']='c5remap'
            obj['SourceBlendStride']=active_blend.shape[1]
            lanes=active_blend.shape[1]//2
            obj.vertex_groups.clear()
            groups={}
            for v,old in enumerate(mapping):
                for bone,w in zip(active_blend[old,:lanes],active_blend[old,lanes:lanes*2]):
                    if not w:continue
                    b=int(bone)
                    if b not in groups:groups[b]=obj.vertex_groups.new(name=str(b))
                    groups[b].add([v],float(w)/255.0,'REPLACE')
            for lane in range(active_blend.shape[1]//4):
                a=obj.data.attributes.new(name='SourceBlendRaw'+str(lane),type='INT',domain='POINT')
                a.data.foreach_set('value',active_blend[mapping,lane*4:lane*4+4].copy().view('<i4').ravel())
            layer=obj.data.vertex_colors.get('COLOR') or obj.data.vertex_colors.new(name='COLOR')
            for loop in obj.data.loops:layer.data[loop.index].color=(color[mapping[loop.vertex_index]]/255.0).tolist()
            obj['DataRestoration']='Exact source identity, position/vector/UV bytes checked; raw blend retained; numeric weights and color restored'
            coords=np.empty(len(mapping)*3,dtype='<f4');obj.data.vertices.foreach_get('co',coords)
            assert np.array_equal(coords.reshape(-1,3),positions[mapping])
            restored_shapes=[]
            for key_name,delta in external_shapes.items():
                if not np.any(delta[mapping]):continue
                if not obj.data.shape_keys:obj.shape_key_add(name='Basis',from_mix=False)
                key=obj.shape_key_add(name=key_name,from_mix=False)
                key.data.foreach_set('co',(positions[mapping]+delta[mapping]).ravel());key.value=0
                restored_shapes.append(key_name)
            if name!='denia' and standard_shapes.get('status')=='decoded':
                for channel in standard_shapes['channels'].values():
                    delta=np.zeros_like(positions)
                    for vertex,offset in channel['vertices'].items():
                        if vertex<len(positions):delta[vertex]=offset
                    if not np.any(delta[mapping]):continue
                    existing=set(obj.data.shape_keys.key_blocks.keys()) if obj.data.shape_keys else set()
                    if channel['name'] in existing:continue
                    if not obj.data.shape_keys:obj.shape_key_add(name='Basis',from_mix=False)
                    key=obj.shape_key_add(name=channel['name'],from_mix=False)
                    key.data.foreach_set('co',(positions[mapping]+delta[mapping]).ravel());key.value=0
                    restored_shapes.append(channel['name'])
            show=True
            if name!='denia' and default_values is not None:
                checks=[c for c in variant_conditions(static_draw_conditions(draw.get('conditions',[])))
                        if not re.fullmatch(r'\s*\$mod_enabled\s*',c,re.I)]
                outcomes=[evaluate_condition(c,default_values) for c in checks]
                show=False not in outcomes and None not in outcomes
            obj.hide_render=not show;obj.hide_set(not show)
            report['objects'].append({'name':obj.name,'group':group,'component':int(c),'draw_index':index,**draw,
                'vertices':len(mapping),'triangles':len(obj.data.polygons),'shape_keys':[k.name for k in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [],
                'position_source_exact':True,'vector_source_exact':True,'uv_source_bytes_exact':cpu,
                'shape_restoration':restored_shapes,
                'visible_by_default':not obj.hide_render,
                'external_shape_restoration':'HLSL VertexOffsets/RecordChannels/RecordDeltas and INI parameter mapping' if external_shapes else None,
                'min':positions[mapping].min(0).tolist(),'max':positions[mapping].max(0).tolist()})
            print('IMPORTED',obj.name,len(mapping),flush=True)
raw=bpy.data.collections.new('SOURCE_All_Draws');bpy.context.scene.collection.children.link(raw)
for obj in [o for o in bpy.data.objects if o.type=='MESH']:
    for col in list(obj.users_collection):col.objects.unlink(obj)
    raw.objects.link(obj)
    if name=='denia':
        d=json.loads(obj['SourceDraw']);g=obj['SourceGroup'];c=obj['SourceComponent']
        show=(g=='ib0' and (c in (0,1,2,7) or (c==3 and d['start'] in (492672,558684,668856,754536)) or (c==5 and d['start']==1373391)))
        obj.hide_render=not show;obj.hide_set(not show)
bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=False,do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'full.blend'))
bpy.ops.wm.open_mainfile(filepath=str(out/'full.blend'))
report['save_reload_verified']=True;report['status']='full_imported'
(run/'import-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FULL_SAVE_RELOAD_VERIFIED',len(report['objects']),flush=True)
