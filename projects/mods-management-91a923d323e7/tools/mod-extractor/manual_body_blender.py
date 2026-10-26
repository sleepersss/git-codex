"""Blender-side save witness and independent deletion-only source verification."""
import bpy
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path


def write(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def modifier_state(obj):
    states=[]
    for modifier in obj.modifiers:
        state={}
        for prop in modifier.bl_rna.properties:
            key=prop.identifier
            if key=='rna_type' or prop.type=='COLLECTION':continue
            value=getattr(modifier,key)
            if prop.type=='POINTER':value=value.name_full if isinstance(value,bpy.types.ID) else str(type(value))
            elif getattr(prop,'is_array',False):value=list(value)
            if value is None or isinstance(value,(str,int,float,bool,list)):state[key]=value
        states.append(state)
    return states


def capture(obj):
    mesh=obj.data
    if hasattr(mesh,'calc_normals_split'):mesh.calc_normals_split()
    source=mesh.attributes.get('SourceVertexIndex')
    indices=[int(x.value) for x in source.data] if source else list(range(len(mesh.vertices)))
    if len(set(indices))!=len(indices):raise ValueError(obj.name+'：源顶点编号重复')
    shapes=mesh.shape_keys
    attributes=[a for a in mesh.attributes if a.domain=='POINT' and not a.name.startswith('.') and a.name not in ('position','select_vert')]
    def attr_value(data):
        for name in ('value','vector','color'):
            if hasattr(data,name):
                v=getattr(data,name);return list(v) if hasattr(v,'__iter__') else v
        raise ValueError('不支持的顶点属性')
    vertices={}
    points=[]
    for v,source_index in zip(mesh.vertices,indices):
        if not all(math.isfinite(x) for x in v.co):raise ValueError('顶点包含非有限值')
        point=obj.matrix_world @ v.co;points.append(list(point))
        vertices[source_index]=digest({'co':list(v.co),
            'weights':sorted((obj.vertex_groups[g.group].name,g.weight) for g in v.groups),
            'attributes':{a.name:attr_value(a.data[v.index]) for a in attributes},
            'shapes':{key.name:list(key.data[v.index].co) for key in shapes.key_blocks} if shapes else {}})
    faces=[]
    for face in mesh.polygons:
        corners=[]
        for i in face.loop_indices:
            loop=mesh.loops[i]
            uv={layer.name:list(layer.data[i].uv) for layer in mesh.uv_layers}
            if not all(math.isfinite(x) for values in uv.values() for x in values):raise ValueError('UV 包含非有限值')
            corners.append((indices[loop.vertex_index],uv,
                {layer.name:list(layer.data[i].color) for layer in mesh.vertex_colors}))
        rotations=[corners[i:]+corners[:i] for i in range(len(corners))]
        faces.append(digest({'corners':min(rotations,key=lambda x:json.dumps(x,sort_keys=True)),
            'material':face.material_index,'smooth':face.use_smooth}))
    mesh.calc_loop_triangles()
    bounds={'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]} if points else None
    return {'vertices':vertices,'faces':faces,'triangles':len(mesh.loop_triangles),'bounds':bounds,
        'matrix':[list(r) for r in obj.matrix_world],
        'materials':[slot.material.name if slot.material else None for slot in obj.material_slots],
        'uv_layers':[a.name for a in mesh.uv_layers],
        'shape_keys':[a.name for a in shapes.key_blocks] if shapes else [],
        'shape_state':{'values':[(a.name,a.value,a.mute) for a in shapes.key_blocks],
            'show_only':obj.show_only_shape_key,'eval_time':shapes.eval_time,
            'use_relative':shapes.use_relative} if shapes else None,
        'modifiers':modifier_state(obj),
        'vertex_groups':[a.name for a in obj.vertex_groups],
        'source_properties':{key:str(obj[key]) for key in obj.keys() if key.startswith('Source')},
        'normals':[list(loop.normal) for loop in mesh.loops],
        'has_source_indices':source is not None}


def verify(session):
    from collections import Counter
    folder=session.parent;d=json.loads(session.read_text(encoding='utf-8'))
    bpy.ops.wm.open_mainfile(filepath=d['full'])
    before={o.name:capture(o) for o in bpy.data.objects if o.type=='MESH'}
    bpy.ops.wm.open_mainfile(filepath=d['working'])
    after={o.name:capture(o) for o in bpy.data.objects if o.type=='MESH'}
    if not after or not sum(len(v['faces']) for v in after.values()):raise ValueError('删减后没有非空网格，本次不生成身体')
    checks=[];changed=set(before)!=set(after)
    for name,current in after.items():
        if name not in before:raise ValueError('新增或重命名的网格无法对应源模型：'+name)
        old=before[name]
        for key in ('matrix','materials','uv_layers','shape_keys','shape_state','modifiers','vertex_groups','source_properties'):
            if current[key]!=old[key]:raise ValueError(name+'：保留源属性发生改变：'+key)
        if not current['faces']:raise ValueError(name+'：保留了空网格，请删除空对象')
        if any(old['vertices'].get(i)!=v for i,v in current['vertices'].items()):
            raise ValueError(name+'：保留顶点、权重或属性被修改；请仅删除多余模型/源面')
        if Counter(current['faces'])-Counter(old['faces']):raise ValueError(name+'：出现新增或改动的源面、UV、颜色或材质索引')
        reduced=len(current['vertices'])<len(old['vertices']) or len(current['faces'])<len(old['faces'])
        changed=changed or reduced
        checks.append({'object':name,'vertices':len(current['vertices']),'triangles':current['triangles'],
            'source_position_exact':True,'source_faces_only':True,'raw_attributes_exact':True,
            'uv_exact':True,'color_exact':True,'weights_exact':True,'shape_targets_exact':True,
            'transform_exact':True,'material_indices_exact':True,
            'modifier_settings_exact':True,'shape_state_exact':True,
            'split_normals_exact':current['normals']==old['normals'] if not reduced else None,
            'split_normals_scope':'exact loop comparison' if not reduced else 'not compared after face deletion'})
    if not changed:
        write(folder/'verification.json',{'status':'unchanged'});return
    bounds=[v['bounds'] for v in after.values() if v['bounds']]
    bounds={'min':[min(b['min'][i] for b in bounds) for i in range(3)],
        'max':[max(b['max'][i] for b in bounds) for i in range(3)]}
    measurements={'mesh_count':len(after),'vertex_count':sum(len(v['vertices']) for v in after.values()),
        'triangle_count':sum(v['triangles'] for v in after.values()),'world_bounds':bounds,
        'dimensions':[bounds['max'][i]-bounds['min'][i] for i in range(3)],
        'units':'Blender world units; not verified centimeters or anatomical dimensions',
        'measurement_scope':'stored base mesh coordinates in world space; unevaluated modifiers and shape poses',
        'objects':[{'name':name,'vertices':len(v['vertices']),'triangles':v['triangles'],
            'world_bounds':v['bounds'],'uv_layers':v['uv_layers'],'shape_keys':v['shape_keys'],
            'vertex_groups':v['vertex_groups']} for name,v in after.items()]}
    removed={'objects':sorted(set(before)-set(after)),
        'vertices':sum(len(v['vertices']) for v in before.values())-measurements['vertex_count'],
        'triangles':sum(v['triangles'] for v in before.values())-measurements['triangle_count']}
    scope='用户在 full.blend 副本中手动删减并保存的剩余源网格；仅核对保留源数据，不推断身体解剖完整性、互斥状态或游戏适配'
    fingerprints={name:digest({'vertices':v['vertices'],'faces':v['faces'],'matrix':v['matrix']}) for name,v in after.items()}
    candidate=folder/'body.blend';shutil.copy2(d['working'],candidate)
    # Reopen the exact output bytes before accepting the saved mesh inventory.
    bpy.ops.wm.open_mainfile(filepath=str(candidate))
    reopened={o.name:capture(o) for o in bpy.data.objects if o.type=='MESH'}
    if reopened!=after:raise ValueError('身体保存重载后数据不一致')
    verification={'status':'passed','checks':checks,'scope':scope,'measurements':measurements,
        'removed':removed,'fingerprints':fingerprints,'full_sha256':d['full_sha256'],'body_sha256':file_hash(candidate)}
    write(folder/'body-source-verification.json',verification)
    write(folder/'body-analysis.json',{'method':'user_saved_deletion','chosen':list(after),'geometry':measurements,'scope':scope})
    write(folder/'body-selection.json',{'method':'user_saved_deletion','meshes':list(after),
        'saved_file_reopened':True,'source_geometry_unchanged':True,'fingerprints':fingerprints,'scope':scope})
    write(folder/'body-decision.json',{'status':'eligible','reason_code':'body_verified','scope':scope,
        'missing_parts':[],'message':'手动删减并保存的剩余模型已核对；身体解剖完整性未自动判定。'})
    # Preview changes are in-memory only; never rewrite the user-saved candidate.
    for obj in bpy.data.objects:
        if obj.type=='MESH':obj.hide_set(False);obj.hide_viewport=False;obj.hide_render=False
    for collection in bpy.data.collections:collection.hide_render=False;collection.hide_viewport=False
    import runpy
    inspector=Path(__file__).resolve().parents[2]/'model-library/inspect_blend.py'
    sys.argv=[str(inspector),'--',str(folder/'body-previews'),'--previews']
    runpy.run_path(str(inspector),run_name='__main__')
    from html import escape
    html='<meta charset="utf-8"><title>手动身体删减记录</title><h1>手动身体删减记录</h1><p>'+escape(scope)+'</p>'
    html+='<p>网格：%s；顶点：%s；三角面：%s。尺寸（Blender 单位）：%s。</p>' % (measurements['mesh_count'],measurements['vertex_count'],measurements['triangle_count'],measurements['dimensions'])
    html+='<p>原 full.blend 已保留。<a href="manual-body.json">测量与处理记录</a> · <a href="body-source-verification.json">源数据核对</a></p>'
    html+='<pre>'+escape(json.dumps({'measurements':measurements,'removed':removed,'checks':checks},ensure_ascii=False,indent=2))+'</pre>'
    (folder/'manual-body.html').write_text(html,encoding='utf-8')
    write(folder/'verification.json',verification)


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];session=Path(args[0]).resolve();mode=args[1]
    if mode=='edit':
        from bpy.app.handlers import persistent
        d=json.loads(session.read_text(encoding='utf-8'))
        @persistent
        def saved(_):
            if Path(bpy.data.filepath).resolve()==Path(d['working']).resolve():
                write(session.parent/'saved.json',{'path':bpy.data.filepath,'sha256':file_hash(bpy.data.filepath)})
        bpy.app.handlers.save_post.append(saved)
    else:verify(session)
