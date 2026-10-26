"""Kernel-owned task lock shared by editor and deletion across app instances."""
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def task_guard(run):
    run=Path(run).resolve();folder=run.parent.parent/'backups/mod-extractor-task-locks'
    for path in (folder,*folder.parents):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('任务锁路径包含链接')
    folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(os.path.normcase(str(run)).encode('utf-8')).hexdigest()
    with (folder/(key+'.guard')).open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:raise ValueError('该处理任务正在被另一个窗口编辑或删除，请先结束该操作') from error
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)
