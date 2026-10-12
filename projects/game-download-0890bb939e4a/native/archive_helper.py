"""On-demand Edge native host. Never execute downloaded files."""
import base64
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import subprocess
import sys
import uuid
import hashlib

def file_signature(path):
    info=path.stat()
    return [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]

def sha256_file(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def verify_extracted(stage,entries):
    checked=[]
    for entry in entries:
        path=stage.joinpath(*PureWindowsPath(entry['Path']).parts)
        if entry.get('Folder')=='+' or re.search(r'(^|\s)D',entry.get('Attributes','')):
            if not path.is_dir():raise ValueError('解压目录缺失')
            continue
        if not path.is_file() or path.stat().st_size!=int(entry.get('Size','0')):raise ValueError('解压文件缺失或尺寸不符')
        checked.append({'path':entry['Path'],'size':path.stat().st_size,'sha256':sha256_file(path)})
    if not checked:raise ValueError('压缩包未包含游戏文件')
    return checked

def normalize_game_layout(stage,members):
    """Remove sole enclosing folders before adding archive metadata."""
    removed=[]
    while True:
        children=list(stage.iterdir())
        if len(children)!=1 or not children[0].is_dir():break
        wrapper=children[0];check_links(wrapper)
        contents=list(wrapper.iterdir())
        if not contents:break
        for child in contents:
            destination=stage/child.name
            if destination.exists():raise ValueError('整理游戏目录时发现名称冲突')
        for child in contents:child.rename(stage/child.name)
        wrapper.rmdir();removed.append(wrapper.name)
        for member in members:
            member.setdefault('archivePath',member['path'])
            parts=PureWindowsPath(member['path']).parts
            if not parts or parts[0]!=wrapper.name:raise ValueError('验证记录与游戏目录不符')
            member['path']=str(PureWindowsPath(*parts[1:]))
    return removed

def delete_verified_source(source,target,folder,signature,digest):
    source=Path(source);folder=Path(folder)
    check_links(folder);check_links(source)
    if source.resolve().parent!=folder.resolve() or not target.is_dir():raise ValueError('源包不在指定IDM目录或归档目录缺失，未删除')
    if file_signature(source)!=signature:raise ValueError('源包发生变化，未删除')
    if os.name=='nt':
        import ctypes, msvcrt
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        handle=kernel.CreateFileW(str(source),0x80000000|0x10000,0,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:raise OSError('源包仍被占用或无法删除，已保留')
        fd=msvcrt.open_osfhandle(int(handle),os.O_RDONLY|os.O_BINARY)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]!=signature or hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise ValueError('源包内容或身份变化，未删除')
            kernel.SetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
            kernel.SetFileInformationByHandle.restype=wintypes.BOOL
            flag=wintypes.BOOL(True)
            if not kernel.SetFileInformationByHandle(handle,4,ctypes.byref(flag),ctypes.sizeof(flag)):raise OSError('Windows拒绝删除，源包已保留')
    else:
        if sha256_file(source)!=digest:raise ValueError('源包内容变化，未删除')
        source.unlink()

HOST = 'com.sleepersss.game_download'
CATEGORIES = {'ACT', 'ADV', 'GAL', 'RPG', 'SLG'}
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
DEFAULT_SEVEN_ZIP = r'D:\1_Software\50_routine\RIME\weasel-0.17.4\7z.exe'

def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip().rstrip('. ')
    if not value or value in {'.', '..'} or RESERVED.match(value):
        raise ValueError('无效或保留的 Windows 文件名')
    if len(value) > 120:
        raise ValueError('游戏名过长，请在插件中缩短')
    return value

def validate_entries(entries):
    if not entries:
        raise ValueError('压缩包没有可解压文件')
    for entry in entries:
        name = entry.get('Path', '')
        path = PureWindowsPath(name)
        if not name or path.is_absolute() or path.drive or name.startswith(('/', '\\')):
            raise ValueError('压缩包含绝对路径')
        for part in re.split(r'[/\\]', name):
            if part in {'', '.', '..'} or safe_name(part) != part:
                raise ValueError('压缩包含不安全文件名或路径')
        if any(entry.get(k, '') not in {'', '-'} for k in ('Symbolic Link', 'Hard Link', 'Copy Link')) or entry.get('Alternate Stream') == '+':
            raise ValueError('压缩包含链接或数据流，拒绝自动解压')

def check_links(path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('目标目录含链接或目录联接')

def target_path(root, category, title):
    if category not in CATEGORIES:
        raise ValueError('未知游戏类型')
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('归档根目录必须是绝对路径')
    check_links(root)
    target = root / category / safe_name(title)
    check_links(target)
    if target.exists():
        raise FileExistsError('游戏目录已存在，保留原目录；请修改游戏名后重试')
    return target

def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise ValueError('消息被截断')
        chunks.extend(part)
    return bytes(chunks)

def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        header += read_exact(stream, 4-len(header))
    size = struct.unpack('<I', header)[0]
    if size > 48 * 1024 * 1024:
        raise ValueError('消息过大')
    return json.loads(read_exact(stream, size).decode('utf-8'))

def write_message(stream, message):
    data = json.dumps(message, ensure_ascii=False).encode('utf-8')
    if len(data) > 1024 * 1024:
        raise ValueError('响应过大')
    stream.write(struct.pack('<I', len(data)) + data)
    stream.flush()

def write_description(folder, metadata):
    dest = folder / '介绍'
    if dest.exists():
        raise FileExistsError('压缩包中已有介绍目录，避免覆盖，请人工处理')
    dest.mkdir()
    title, text, source = [str(metadata.get(k, '')) for k in ('title', 'text', 'source')]
    (dest/'介绍.txt').write_text(title + '\n\n' + text + '\n\n来源：' + source, encoding='utf-8')
    pictures = []
    failures = list(metadata.get('imageErrors', []))
    images = metadata.get('images', [])
    if len(images) > 30:
        raise ValueError('图片超过30张')
    for index, image in enumerate(images, 1):
        ext = {'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif'}.get(image.get('mime'))
        if not ext:
            failures.append('不支持的图片格式'); continue
        raw = base64.b64decode(image['data'], validate=True)
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError('单张图片超过5MB')
        name = f'{index:02d}.{ext}'
        (dest/name).write_bytes(raw)
        pictures.append(f'<img src="{name}" alt="游戏介绍图片 {index}">')
    output = '<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{max-width:1000px;margin:40px auto;font:18px/1.7 sans-serif;padding:20px}pre{white-space:pre-wrap}img{max-width:100%;display:block;margin:20px 0}</style><h1>'+html.escape(title)+'</h1><pre>'+html.escape(text)+'</pre>'+''.join(pictures)+'<p>来源：'+html.escape(source)+'</p>'
    (dest/'介绍.html').write_text(output, encoding='utf-8')
    (dest/'记录.json').write_text(json.dumps({'title':title,'source':source,'imageCount':len(pictures),'imageErrors':failures},ensure_ascii=False,indent=2),encoding='utf-8')
    return failures

def run_7z(exe, args, password, timeout=3600):
    if not Path(exe).is_file():
        raise FileNotFoundError('找不到7-Zip，请在设置中指定7z.exe')
    result = subprocess.run([exe, *args, '-sccUTF-8', '-p'+password], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    if result.returncode != 0:
        if 'Wrong password' in output or 'Data Error' in output:
            raise ValueError('密码错误或压缩包损坏；原下载包保留')
        raise ValueError('7-Zip处理失败；请检查压缩包完整性与工具版本')
    return output

def inspect_archive(exe, archive, password):
    output = run_7z(exe, ['l','-slt',str(archive)], password, timeout=120)
    if '\n----------' not in output:
        raise ValueError('无法读取压缩包列表')
    header, content = output.split('\n----------',1)
    match = re.search(r'^Type = (.+)$',header,re.M)
    kind = match.group(1).strip() if match else ''
    if kind.lower() not in {'7z','rar','rar5','zip'}:
        raise ValueError('非支持的压缩包格式：'+kind)
    entries=[]
    for block in re.split(r'\r?\n\s*\r?\n',content.strip()):
        fields=dict(line.split(' = ',1) for line in block.splitlines() if ' = ' in line)
        if 'Path' in fields: entries.append(fields)
    validate_entries(entries)
    return kind, entries

def archive_game(request, progress=lambda text: None):
    settings, metadata = request['settings'], request['metadata']
    archive=Path(request['archive'])
    if not archive.is_absolute() or not archive.is_file() or archive.is_symlink():
        raise ValueError('下载文件不存在或不是普通文件')
    if archive.suffix.lower() not in {'.exe','.7z','.rar','.zip'}:
        raise ValueError('下载文件后缀不受支持')
    if request.get('idm'):
        check_links(Path(settings['idmFolder']))
        if archive.resolve().parent!=Path(settings['idmFolder']).resolve():raise ValueError('源包不在指定IDM目录，未处理')
    target=target_path(settings['root'],metadata['category'],metadata['title'])
    exe=settings.get('sevenZip') or DEFAULT_SEVEN_ZIP
    password=str(settings.get('password',''))
    signature=file_signature(archive)
    source_hash=sha256_file(archive)
    progress('识别格式与检查压缩包路径')
    kind,entries=inspect_archive(exe,archive,password)
    target.parent.mkdir(parents=True,exist_ok=True)
    required=sum(int(e.get('Size','0')) for e in entries)
    if shutil.disk_usage(target.parent).free < required + 256*1024*1024:
        raise ValueError('归档盘可用空间不足')
    progress('校验密码与压缩包完整性')
    run_7z(exe,['t',str(archive)],password)
    stage=target.parent/('.game-download-'+uuid.uuid4().hex)
    stage.mkdir()
    try:
        progress('解压到临时目录')
        run_7z(exe,['x',str(archive),'-o'+str(stage),'-y'],password)
        if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in stage.rglob('*')):
            raise ValueError('解压结果含链接')
        progress('验证解压文件并记录SHA256')
        members=verify_extracted(stage,entries)
        wrappers=normalize_game_layout(stage,members)
        errors=write_description(stage,metadata)
        (stage/'验证记录.json').write_text(json.dumps({'sourceSHA256':source_hash,'removedWrappers':wrappers,'files':members},ensure_ascii=False,indent=2),encoding='utf-8')
        if file_signature(archive)!=signature:raise ValueError('下载源包在处理期间发生变化，未发布归档')
        (stage/'下载记录.json').write_text(json.dumps({'archive':str(archive),'format':kind,'title':metadata['title'],'category':metadata['category'],'imageErrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        check_links(target)
        if target.exists(): raise FileExistsError('目标目录在处理期间已创建，拒绝覆盖')
        stage.rename(target)
        deleted=False;cleanup_warning=''
        if request.get('idm') and settings.get('deleteArchive',True):
            if errors:cleanup_warning='介绍图片未全部保存，源包保留'
            else:
                try:
                    progress('归档验证成功，删除本任务IDM源包')
                    delete_verified_source(archive,target,Path(settings['idmFolder']),signature,source_hash);deleted=True
                except Exception as error:cleanup_warning=str(error)
        try:(target/'下载记录.json').write_text(json.dumps({'archive':str(archive),'format':kind,'title':metadata['title'],'category':metadata['category'],'imageErrors':errors,'sourceDeleted':deleted,'cleanupWarning':cleanup_warning},ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError:cleanup_warning+='；归档完成，但清理状态记录未能更新'
        return {'ok':True,'path':str(target),'format':kind,'imageErrors':errors,'sourceDeleted':deleted,'cleanupWarning':cleanup_warning}
    except Exception as error:
        raise ValueError(f'{error}；临时结果保留在 {stage}') from error

def main():
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    while True:
        try:
            request=read_message(sys.stdin.buffer)
            if request is None: break
            if request.get('action')=='ping':
                result={'ok':True,'version':'0.2.2','sevenZip':DEFAULT_SEVEN_ZIP,'idm':True}
            elif request.get('action')=='archive':
                result=archive_game(request,lambda text:write_message(sys.stdout.buffer,{'progress':text}))
            elif request.get('action')=='prepare_idm':
                import idm_bridge
                result=idm_bridge.prepare_watch(request['folder'],request['expected'],request['jobId'])
            elif request.get('action')=='poll_idm':
                import idm_bridge
                result=idm_bridge.poll_watch(request['token'],request.get('urlHashes',request.get('urls',[])))
            elif request.get('action')=='list_idm':
                import idm_bridge
                result={'ok':True,'files':idm_bridge.list_files(request['folder'],request['expected'])}
            elif request.get('action')=='archive_idm':
                import idm_bridge
                state,archive=idm_bridge.claim_ready(request['token'])
                if Path(request['settings']['idmFolder']).resolve()!=Path(state['folder']).resolve():raise ValueError('IDM目录设置已变化，未归档')
                result=archive_game({**request,'archive':str(archive),'idm':True},lambda text:write_message(sys.stdout.buffer,{'progress':text}))
            else: raise ValueError('未知操作')
            write_message(sys.stdout.buffer,result)
        except Exception as error:
            write_message(sys.stdout.buffer,{'ok':False,'error':str(error)[:2000]})

if __name__=='__main__': main()
