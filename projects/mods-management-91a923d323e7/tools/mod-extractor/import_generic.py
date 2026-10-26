"""Blender direct reader with exact source positions/topology and raw attributes."""
import bpy,numpy as np,json,sys,hashlib
from pathlib import Path
from bpy_extras.io_utils import axis_conversion
run=Path(sys.argv[sys.argv.index('--')+1]);root=run/'input'
plans=json.loads((run/'mesh-plan.json').read_text(encoding='utf-8'))
bpy.context.preferences.filepaths.save_version=0
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
cache={};expected={};report=[]
def data(r):
    p=root/r['file'];stride=int(r.get('stride','0'))
    key=(str(p),stride)
    if key not in cache:
        a=np.fromfile(p,dtype='u1')
        if not stride or len(a)%stride:raise ValueError('资源 stride 不匹配：'+str(p))
        cache[key]=a.reshape(-1,stride)
    return cache[key]
def digest(obj):
    pos=np.empty(len(obj.data.vertices)*3,dtype='<f4');obj.data.vertices.foreach_get('co',pos)
    idx=np.empty(len(obj.data.loops),dtype='<i4');obj.data.loops.foreach_get('vertex_index',idx)
    h=hashlib.sha256(pos.tobytes()+idx.tobytes())
    matrix=[[round(float(v),6) if abs(v)>=.0000005 else 0 for v in row] for row in obj.matrix_world]
    h.update(json.dumps({'matrix':matrix,'hidden':obj.hide_render},sort_keys=True).encode())
    for a in sorted(obj.data.attributes,key=lambda a:a.name):
        if a.data_type=='INT' and a.domain=='POINT':
            values=np.empty(len(a.data),dtype='<i4');a.data.foreach_get('value',values);h.update(a.name.encode()+values.tobytes())
    for layer in obj.data.uv_layers:
        values=np.empty(len(layer.data)*2,dtype='<f4');layer.data.foreach_get('uv',values);h.update(layer.name.encode()+values.tobytes())
    for layer in obj.data.vertex_colors:
        values=np.empty(len(layer.data)*4,dtype='<f4');layer.data.foreach_get('color',values);h.update(layer.name.encode()+values.tobytes())
    groups={'names':[g.name for g in obj.vertex_groups],'vertices':[(v.index,[(link.group,float(link.weight)) for link in v.groups]) for v in obj.data.vertices if v.groups]}
    h.update(json.dumps(groups,separators=(',',':')).encode())
    return h.hexdigest()
for number,plan in enumerate(plans):
    b=plan['bindings'];posraw=data(b['vb0']);positions=posraw[:,:12].copy().view('<f4').reshape(-1,3)
    if not np.isfinite(positions).all():raise ValueError('顶点包含非有限数值')
    ir=b['ib'];indices=np.fromfile(root/ir['file'],dtype='<u2' if ir['format']=='R16_UINT' else '<u4')
    start,count,base=plan['start'],plan['count'],plan['base']
    if count%3 or start+count>len(indices):raise ValueError('三角面绘制范围超出缓冲区：'+plan['section'])
    corners=indices[start:start+count].astype('int64')+base
    if corners.min()<0 or corners.max()>=len(positions):raise ValueError('索引越界：'+plan['section'])
    mapping,compact=np.unique(corners,return_inverse=True);p=positions[mapping]
    mesh=bpy.data.meshes.new(plan['section']);mesh.from_pydata(p.tolist(),[],compact.reshape(-1,3).tolist());mesh.update()
    obj=bpy.data.objects.new('%03d_%s'%(number,plan['section']),mesh);bpy.context.collection.objects.link(obj)
    obj['SourceDraw']=json.dumps(plan,ensure_ascii=False);obj['StaticVariantsIncluded']=True
    if plan.get('game')=='HSR':
        obj.matrix_world=axis_conversion(from_forward='-Z',from_up='Y').to_4x4()
        obj['SourceAxisConvention']='Y up / -Z forward; object transform to Blender Z up, source coordinates retained'
    obj.hide_render=not plan.get('visible_by_default',True);obj.hide_set(obj.hide_render)
    a=mesh.attributes.new('SourceVertexIndex','INT','POINT');a.data.foreach_set('value',mapping.astype('i4'))
    loopnormals=None
    if posraw.shape[1] in (40,56):loopnormals=posraw[mapping,12:24].copy().view('<f4').reshape(-1,3)[compact]
    attribute_notes=[]
    # Keep every bound vertex byte, including packed lanes that cannot be interpreted safely.
    for slot,r in b.items():
        if slot=='ib':continue
        raw=data(r)
        if len(raw)!=len(positions):
            raise ValueError('绑定属性顶点数量不一致：'+slot+' / '+r['file'])
        selected=raw[mapping]
        if 'vector' in r['name'].lower() and selected.shape[1]==8:
            loopnormals=(selected[:,4:7].copy().view('i1').astype('f4')/127)[compact]
        if 'color' in r['name'].lower() and selected.shape[1]==4:
            color=mesh.vertex_colors.new(name='SourceColor');color.data.foreach_set('color',(selected.astype('f4')[compact]/255).reshape(-1))
        padded=np.pad(selected,((0,0),(0,(-selected.shape[1])%4)))
        for lane in range(padded.shape[1]//4):
            a=mesh.attributes.new('Raw_'+slot+'_'+str(lane),'INT','POINT')
            a.data.foreach_set('value',padded[:,lane*4:lane*4+4].copy().view('<i4').reshape(-1))
        if 'texcoord' in r['name'].lower():
            stride=int(r.get('stride',0));hsr=plan.get('game')=='HSR'
            if hsr and stride in (8,12,16,20,28):
                color=mesh.vertex_colors.new(name='SourceColor');color.data.foreach_set('color',(selected[:,:4].astype('f4')[compact]/255).reshape(-1))
                half=stride in (8,16)
                if stride==12:
                    raw=data(r)[:,4:]
                    f=raw.copy().view('<f4').reshape(-1,2);hf=raw.copy().view('<f2').reshape(-1,4).astype('f4')
                    half=bool(np.isfinite(hf).all() and np.max(np.abs(hf))<=4 and np.max(np.abs(f))<.05 and np.ptp(hf,axis=0).max()>.2)
                    attribute_notes.append('HSR stride12 UV layout inferred from complete buffer ranges; raw bytes retained')
                uv=selected[:,4:].copy().view('<f2' if half else '<f4').reshape(len(mapping),-1).astype('f4');offsets=range(0,uv.shape[1],2)
            elif stride==16:
                uv=selected.copy().view('<f2').reshape(len(mapping),-1).astype('f4');offsets=range(0,8,2)
            elif stride==20:
                uv=selected[:,4:].copy().view('<f4').reshape(len(mapping),4);offsets=(0,2)
            else:offsets=()
            for i in offsets:
                value=uv[:,i:i+2].copy()
                if hsr:value[:,1]=1-value[:,1]
                if np.isfinite(value).all():
                    layer=mesh.uv_layers.new(name='SourceUV_'+str(i//2));layer.data.foreach_set('uv',value[compact].reshape(-1))
                else:attribute_notes.append('UV contains non-finite values; semantic layer omitted, raw bytes retained')
            if not offsets:attribute_notes.append('UV layout unresolved; raw bytes retained')
        if 'blend' in r['name'].lower() and selected.shape[1] in (8,16,32):
            stride=selected.shape[1]
            if plan.get('game')=='HSR' and stride!=32:
                attribute_notes.append('Packed HSR weights unresolved; raw bytes retained');continue
            if plan.get('game') in ('WW','WWMI') and stride in (8,16):
                # WWMI packed layout: N uint8 bone indices followed by N uint8 weights.
                # N is eight for a 16-byte stream, not four plus unused padding.
                lanes=stride//2;bones=selected[:,:lanes];weights=selected[:,lanes:].astype('f4')/255
            else:
                weights=selected[:,:16].copy().view('<f4').reshape(-1,4) if stride==32 else selected[:,:4].astype('f4')/255
                bones=selected[:,16:].copy().view('<u4').reshape(-1,4) if stride==32 else selected[:,8:12] if stride==16 else selected[:,4:8]
            for bone in np.unique(bones):
                group=obj.vertex_groups.new(name=str(int(bone)))
                for lane in range(weights.shape[1]):
                    for v in np.flatnonzero((bones[:,lane]==bone)&(weights[:,lane]>0)):group.add([int(v)],float(weights[v,lane]),'ADD')
    if loopnormals is not None and np.isfinite(loopnormals).all():
        mesh.use_auto_smooth=True;mesh.normals_split_custom_set(loopnormals.tolist())
    # Verify source identity before and after Blender serialization.
    savedpos=np.empty(p.size,dtype='f4');mesh.vertices.foreach_get('co',savedpos)
    savedidx=np.empty(count,dtype='i4');mesh.loops.foreach_get('vertex_index',savedidx)
    assert np.array_equal(savedpos.reshape(-1,3),p) and np.array_equal(mapping[savedidx],corners)
    expected[obj.name]=digest(obj);report.append({'object':obj.name,'vertices':len(p),'triangles':count//3,'source_position':b['vb0']['file'],'source_index':ir['file'],'draw_start':start,'visible_by_default':not obj.hide_render,'uv_layers':len(mesh.uv_layers),'attribute_notes':attribute_notes,'runtime_attributes_unresolved':plan.get('unresolved_runtime_attributes',{})})
out=run/'models';out.mkdir(exist_ok=True);full=out/'full.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(full));bpy.ops.wm.open_mainfile(filepath=str(full))
assert {o.name:digest(o) for o in bpy.data.objects if o.type=='MESH'}==expected
(run/'generic-verification.json').write_text(json.dumps({'status':'passed','objects':report,'mesh_count':len(report),'vertices':sum(r['vertices'] for r in report),'triangles':sum(r['triangles'] for r in report),'fingerprints':expected,'checks':['source_position_exact','source_index_exact','saved_reopened_geometry_and_retained_attributes_exact','resolved_bound_vertex_bytes_retained']},ensure_ascii=False,indent=2),encoding='utf-8')
