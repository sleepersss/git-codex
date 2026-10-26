"""Decode on-disk WWMI 128-channel ShapeKey tables. Never execute source HLSL."""
import re
from pathlib import Path
import numpy as np

NAMED=re.compile(r'shapekey_id\s*=\s*(\d+).*?shapekey_value\s*=\s*\$(\w+)',re.S|re.I)


def named_channels(ini_text):
    return {int(channel):name for channel,name in NAMED.findall(ini_text or '')}


def _xyz_rows(vertex_offset_path,entry_count):
    data=Path(vertex_offset_path).read_bytes()
    half_rows=entry_count*12
    float_rows=entry_count*24
    if len(data)==half_rows:
        packed=np.frombuffer(data,dtype='<f2').reshape(entry_count,6)
        return packed[:,:3].astype('<f4'),'wwmi_128_offset_f16'
    if len(data)==float_rows:
        packed=np.frombuffer(data,dtype='<f4').reshape(entry_count,6)
        return packed[:,:3].copy(),'wwmi_128_offset'
    if len(data)%24==0:
        packed=np.frombuffer(data,dtype='<f4').reshape(-1,6)
        return packed[:,:3].copy(),'wwmi_128_offset'
    raise ValueError('ShapeKeyVertexOffset 行宽无法与顶点表对齐：%s bytes, %s ids'%(len(data),entry_count))


def _ranges(starts,data_end):
    starts=[int(v) for v in starts]
    starts.append(data_end if starts[-1]<data_end else starts[-1])
    return list(zip(starts[:-1],starts[1:]))


def _add_entries(vertices,vertex_ids,xyz,start,stop):
    rows=len(xyz)
    for entry in range(int(start),int(stop)):
        if entry>=len(vertex_ids) or entry>=rows:break
        delta=xyz[entry]
        if not np.any(delta):continue
        if not np.isfinite(delta).all():
            raise ValueError('形态键偏移含非有限值：entry %s'%entry)
        vertices[int(vertex_ids[entry])]=[float(delta[0]),float(delta[1]),float(delta[2])]


def load_shapekeys(meshes,ini_text=None,prefix=''):
    meshes=Path(meshes)
    offset_path=meshes/(prefix+'ShapeKeyOffset.buf')
    vertex_id_path=meshes/(prefix+'ShapeKeyVertexId.buf')
    vertex_offset_path=meshes/(prefix+'ShapeKeyVertexOffset.buf')
    names=named_channels(ini_text)
    if not all(path.is_file() for path in (offset_path,vertex_id_path,vertex_offset_path)):
        return {'status':'absent','channels':{},'named':names,'layout':'wwmi_128_offset'}
    offsets=np.fromfile(offset_path,dtype='<u4')
    if len(offsets)<128:
        raise ValueError('ShapeKeyOffset 不足 128 通道：'+str(offset_path))
    vertex_ids=np.fromfile(vertex_id_path,dtype='<u4')
    xyz,layout=_xyz_rows(vertex_offset_path,len(vertex_ids))
    batches=[_ranges(offsets[:128],len(vertex_ids) if len(offsets)==128 else int(offsets[127]))]
    if len(offsets)>=256 and int(offsets[128])==0 and int(offsets[127])+int(offsets[255])==len(vertex_ids):
        base=int(offsets[127])
        batches.append([(base+start,base+stop) for start,stop in _ranges(offsets[128:256],int(offsets[255]))])
        layout=layout+'_batched'
    channels={}
    for channel in range(128):
        vertices={}
        for batch in batches:
            if channel>=len(batch):break
            start,stop=batch[channel]
            _add_entries(vertices,vertex_ids,xyz,start,stop)
        if vertices:
            channels[channel]={'name':names.get(channel,'Deform %s'%channel),'vertices':vertices}
    return {'status':'decoded','channels':channels,'named':names,'layout':layout,
            'channel_count':len(channels),'vertex_rows':len(vertex_ids),'batches':len(batches)}
