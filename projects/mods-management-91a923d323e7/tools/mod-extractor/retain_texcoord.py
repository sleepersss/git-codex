"""Retain complete original texcoord bytes, including ambiguous packed payloads."""
import bpy,numpy as np,sys,json
from pathlib import Path
run=Path(sys.argv[sys.argv.index('--')+1]).resolve();job=json.loads((run/'job.json').read_text(encoding='utf-8'))
bpy.context.preferences.filepaths.save_version=0
decision=json.loads((run/'body-decision.json').read_text(encoding='utf-8'))
for role in (('full','body') if decision['status']=='eligible' else ('full',)):
    path=run/'models'/f'{role}.blend';bpy.ops.wm.open_mainfile(filepath=str(path))
    for obj in [o for o in bpy.data.objects if o.type=='MESH']:
        group=obj['SourceGroup'];prefix=group+'_' if group else ''
        tex=np.fromfile(Path(job['main_ini']).parent/'Meshes'/(prefix+'TexCoord.buf'),dtype='u1').reshape(-1,16)
        mapping=np.empty(len(obj.data.vertices),dtype=np.int32);obj.data.attributes['SourceVertexIndex'].data.foreach_get('value',mapping)
        for lane in range(4):
            attr=obj.data.attributes.get('SourceTexcoordRaw'+str(lane)) or obj.data.attributes.new(name='SourceTexcoordRaw'+str(lane),type='INT',domain='POINT')
            attr.data.foreach_set('value',tex[mapping,lane*4:lane*4+4].copy().view('<i4').ravel())
        mapping_uv={'TEXCOORD'+(str(i) if i else '')+'.xy':i for i in range(4)}
        if job['name']=='iuno':
            # This lane contains non-finite half interpretations in component3.
            # Herta silently converted them to zero. Park bytes instead of claiming a valid UV.
            layer=obj.data.uv_layers.get('TEXCOORD1.xy')
            if layer:obj.data.uv_layers.remove(layer)
            mapping_uv.pop('TEXCOORD1.xy')
            obj['AmbiguousTexcoordLane']='Bytes4..7 retained exactly as SourceTexcoordRaw1; installed layout supports packed color here, shader semantics unverified'
        ambiguous=[]
        for layer_name,lane in list(mapping_uv.items()):
            half=tex[mapping,lane*4:lane*4+4].copy().view('<f2')
            nonfinite=int(np.count_nonzero(~np.isfinite(half)))
            if not nonfinite:continue
            # Packed or otherwise unexplained bytes cannot be valid finite UV.
            # Preserve them above, rather than accepting Herta's zero substitution.
            layer=obj.data.uv_layers.get(layer_name)
            if layer:obj.data.uv_layers.remove(layer)
            mapping_uv.pop(layer_name)
            ambiguous.append({'lane':lane,'nonfinite_half_values':nonfinite,
                'raw_attribute':'SourceTexcoordRaw'+str(lane),
                'status':'raw_bytes_retained_semantics_unverified'})
        if ambiguous:obj['AmbiguousTexcoordLanes']=json.dumps(ambiguous)
        obj['UVSourceLaneMap']=json.dumps(mapping_uv)
        if role=='full' and job['name']=='denia' and obj['SourceGroup']!='ib0':
            obj.hide_render=True;obj.hide_set(True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    if role=='body':
        selection=json.loads((run/'body-selection.json').read_text(encoding='utf-8'))
        selection['meshes']=[{'name':o.name,'vertices':len(o.data.vertices),'triangles':len(o.data.polygons),'uv_layers':len(o.data.uv_layers),
                             'vertex_groups':len(o.vertex_groups),'shape_keys':len(o.data.shape_keys.key_blocks) if o.data.shape_keys else 0} for o in bpy.data.objects if o.type=='MESH']
        selection['raw_texcoord_retained']=True
        (run/'body-selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
print('RAW_TEXCOORD_RETAINED; non-finite half lanes parked per mesh; source semantics unverified')
