"""Confirmed record deletion with verified recovery archives and bounded paths."""
import hashlib
import json
import os
import queue
import re
import shutil
import stat
import threading
import uuid
import zipfile
from pathlib import Path
from runner import Library,locked,read_json,write_json,sha256,now
from task_guard import task_guard


def linked(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()) or bool(
        getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))


def checked_directory(path,root):
    path=Path(os.path.abspath(path));root=Path(os.path.abspath(root))
    if path==root or not path.is_relative_to(root):raise ValueError('删除目录超出允许范围')
    for candidate in (root,*reversed(path.relative_to(root).parents)):
        candidate=candidate if candidate==root else root/candidate
        if candidate.exists() and linked(candidate):raise ValueError('链接目录不参与删除：'+str(candidate))
    if linked(path) or not path.is_dir() or path.resolve()!=path:raise ValueError('删除目标不是独立普通目录')
    return path


def ordinary_files(path):
    path=Path(path);files=[]
    if linked(path):raise ValueError('链接目录不参与删除')
    def fail(error):raise error
    for base,dirs,names in os.walk(path,followlinks=False,onerror=fail):
        for name in dirs+names:
            file=Path(base,name)
            if linked(file):raise ValueError('链接文件不参与删除：'+str(file))
            if file.is_file():files.append(file)
            elif not file.is_dir():raise ValueError('目标包含非普通文件')
    return sorted(files)


def archive_directory(target,recovery_root,kind,ident):
    target=Path(target);recovery_root=Path(os.path.abspath(recovery_root))
    for ancestor in (recovery_root,*recovery_root.parents):
        if ancestor.exists() and linked(ancestor):raise ValueError('恢复目录路径包含链接')
    if recovery_root==target or recovery_root.is_relative_to(target):raise ValueError('恢复归档不能位于删除目标内')
    recovery_root.mkdir(parents=True,exist_ok=True)
    if linked(recovery_root):raise ValueError('恢复目录不能是链接')
    archive=recovery_root/(ident+'-'+uuid.uuid4().hex[:12]+'.zip');temporary=archive.with_suffix('.partial')
    files=ordinary_files(target);rows=[]
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for file in files:
            before=file.stat();h=hashlib.sha256();name=file.relative_to(target).as_posix()
            with file.open('rb') as source,z.open('payload/'+name,'w',force_zip64=True) as dest:
                for block in iter(lambda:source.read(1024*1024),b''):h.update(block);dest.write(block)
            after=file.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('归档期间文件发生变化，未删除')
            rows.append({'path':name,'size':after.st_size,'mtime_ns':after.st_mtime_ns,'sha256':h.hexdigest()})
        manifest={'kind':kind,'id':ident,'original_directory':str(target),'at':now(),'files':rows}
        z.writestr('recovery-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(temporary) as z:
        for row in rows:
            h=hashlib.sha256()
            with z.open('payload/'+row['path']) as source:
                for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
            if h.hexdigest()!=row['sha256']:raise ValueError('恢复归档读回核验失败，未删除')
    # Verify the source still has precisely the archived inventory before removal.
    current=ordinary_files(target)
    if [p.relative_to(target).as_posix() for p in current]!=[r['path'] for r in rows]:raise ValueError('归档后目录内容变化，未删除')
    for file,row in zip(current,rows):
        if file.stat().st_size!=row['size'] or sha256(file)!=row['sha256']:raise ValueError('归档后文件内容变化，未删除')
    temporary.replace(archive)
    return {'archive':str(archive),'archive_sha256':sha256(archive),'files':len(rows),'bytes':sum(r['size'] for r in rows),'verified':True}


def remove_staged(path,allowed_root):
    path=checked_directory(path,allowed_root);ordinary_files(path)
    def readonly(function,name,error):
        file=Path(name)
        if not isinstance(error,PermissionError) or linked(file) or not file.resolve().is_relative_to(path):raise error
        if not getattr(file.stat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_READONLY',1):raise error
        file.chmod(stat.S_IWRITE);function(name)
    shutil.rmtree(path,onexc=readonly)


def delete_task(run,work_root,library_root):
    work=Path(work_root).absolute();run=checked_directory(run,work)
    if run.parent!=work or not re.fullmatch(r'mod-extraction-[a-z0-9_-]+-\d{8}-[0-9a-f]{8}',run.name):
        raise ValueError('只能删除工作目录中的提取任务')
    job=read_json(run/'job.json') if (run/'job.json').is_file() else {}
    result=read_json(run/'pipeline-result.json');library=Path(library_root).resolve()
    if result.get('status') not in ('passed','failed','cancelled'):raise ValueError('任务尚未结束，不能删除')
    if job.get('library_root') and Path(job['library_root']).resolve()!=library:raise ValueError('任务来自另一素材库，不能删除')
    protected=[library]+([Path(job['source']).resolve()] if job.get('source') else [])
    if any(run==p or run.is_relative_to(p) or p.is_relative_to(run) for p in protected):
        raise ValueError('任务与原 Mod 或素材库重叠，不能删除')
    recovery=work.parent/'backups/mod-extractor-deletions/tasks';lib=Library(library)
    with task_guard(run),locked(lib):
        record=archive_directory(run,recovery,'task',run.name)
        pending=recovery/'pending';pending.mkdir(exist_ok=True)
        checked_directory(pending,recovery)
        stage=pending/(run.name+'-'+uuid.uuid4().hex[:8]);checked_directory(run,work)
        if stage.exists() or linked(pending):raise ValueError('删除暂存目录异常')
        run.rename(stage)
        record.update(status='deleted',kind='task',original_directory=str(run),at=now())
        try:remove_staged(stage,pending)
        except OSError as error:record.update(status='deleted_cleanup_pending',pending=str(stage),cleanup_error=str(error))
        write_json(Path(record['archive']).with_suffix('.json'),record)
    return record


def delete_asset(library_root,asset_id):
    lib=Library(library_root)
    checked_directory(lib.root/'cache',lib.root)
    if not re.fullmatch(r'(WW|HSR|ZZZ)-\d{6}',asset_id):raise ValueError('素材编号无效')
    with locked(lib):
        metadata,doc=lib.find(asset_id);target=checked_directory(metadata.parent,lib.root/'models')
        if target.name!=asset_id or target.parent.parent.name!=doc['game']:raise ValueError('素材目录与编号不符')
        for path,other in lib.documents()[0]:
            if other['id']==asset_id:continue
            for file in other.get('files',{}).values():
                stored=lib.inside(file['path'])
                if stored==target or stored.is_relative_to(target):raise ValueError('其他素材仍引用此目录：'+other['id'])
        recovery=lib.root/'history/deleted-assets';record=archive_directory(target,recovery,'asset',asset_id)
        tombstone=Path(record['archive']).with_suffix('.json')
        record.update(id=asset_id,kind='asset',at=now(),status='prepared',original_directory=str(target))
        write_json(tombstone,record)  # permanently reserve the ID before it leaves active records
        pending=lib.root/'cache/delete-staging';pending.mkdir(exist_ok=True)
        checked_directory(pending,lib.root)
        stage=pending/(asset_id+'-'+uuid.uuid4().hex[:12]);checked_directory(target,lib.root/'models')
        target.rename(stage)
        try:lib.rebuild()
        except Exception:
            stage.rename(target);record['status']='rolled_back';write_json(tombstone,record);raise
        record['status']='deleted'
        try:remove_staged(stage,pending)
        except OSError as error:record.update(status='deleted_cleanup_pending',pending=str(stage),cleanup_error=str(error))
        write_json(tombstone,record)
    return record


class DeletionService:
    def __init__(self):self.thread=None;self.events=queue.Queue()
    @property
    def busy(self):return self.thread is not None and self.thread.is_alive()
    def start(self,kind,**args):
        if self.busy:raise ValueError('删除操作尚未结束')
        def work():
            try:result={'ok':True,**(delete_task(**args) if kind=='task' else delete_asset(**args))}
            except Exception as error:result={'ok':False,'kind':kind,'error':str(error)}
            self.events.put(result)
        self.thread=threading.Thread(target=work,daemon=True);self.thread.start()
    def drain(self):
        result=[]
        while True:
            try:result.append(self.events.get_nowait())
            except queue.Empty:return result
