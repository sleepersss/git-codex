"""One isolated, save-aware manual body session; original full remains read-only."""
import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from runner import read_json,write_json,sha256,now
from app_paths import resource_root
from task_guard import task_guard


def prepare_session(run,blender=None):
    run=Path(run).resolve(strict=True);result=read_json(run/'pipeline-result.json')
    if result.get('status')!='passed' or result.get('full_status')!='verified':
        raise ValueError('请先选择已核对的完整 Mod 提取任务')
    full=run/'models/full.blend'
    if not full.is_file() or sha256(full)!=result['files']['full']['sha256']:
        raise ValueError('完整模型哈希改变，未打开编辑')
    folder=run/'manual-body'/uuid.uuid4().hex[:12];folder.mkdir(parents=True)
    working=folder/'full.blend';shutil.copy2(full,working)
    if sha256(working)!=sha256(full):raise ValueError('工作副本核对失败')
    session=folder/'session.json'
    write_json(session,{'run':str(run),'full':str(full),'working':str(working),
        'full_sha256':sha256(full),'pipeline_sha256':sha256(run/'pipeline-result.json'),
        'blender':blender or read_json(run/'job.json').get('blender'),'started_at':now()})
    return session


def verify_session(session):
    session=Path(session);d=read_json(session)
    script=resource_root()/'tools/mod-extractor/manual_body_blender.py'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (session.parent/'verification.log').open('wb') as log:
        subprocess.run([d['blender'],'--background','--factory-startup','--disable-autoexec',
            '--python-exit-code','1','--python',str(script),'--',str(session),'verify'],
            stdout=log,stderr=subprocess.STDOUT,timeout=300,check=True,creationflags=flags)
    return read_json(session.parent/'verification.json')


def finish_session(session,exit_code):
    session=Path(session);folder=session.parent;d=read_json(session);run=Path(d['run']);working=Path(d['working'])
    outcome={'at':now(),'session':str(session),'blender_exit':exit_code}
    def finish(status,message,**extra):
        outcome.update(status=status,message=message,**extra);write_json(folder/'outcome.json',outcome);return outcome
    try:
        if exit_code:return finish('failed','Blender 异常退出，本次未生成身体；编辑副本和日志已保留。')
        witness=folder/'saved.json'
        if not witness.exists() or not working.is_file() or sha256(working)==d['full_sha256']:
            return finish('unchanged','未保存删减结果，本次不生成 body.blend。')
        saved=read_json(witness)
        if Path(saved['path']).resolve()!=working.resolve() or saved['sha256']!=sha256(working):
            raise ValueError('保存记录与编辑副本不一致；请保存到打开的 full.blend 后退出')
        if sha256(Path(d['full']))!=d['full_sha256'] or sha256(run/'pipeline-result.json')!=d['pipeline_sha256']:
            raise ValueError('编辑期间原任务发生变化，本次结果仅保留在独立目录')
        verified=verify_session(session)
        if verified['status']=='unchanged':return finish('unchanged','模型没有删减，本次不生成 body.blend。')
        if verified['status']!='passed':raise ValueError(verified.get('message','删减后的源网格核对失败'))
        candidate=folder/'body.blend'
        if sha256(candidate)!=sha256(working):raise ValueError('身体候选与实际保存文件不同')
        if sha256(Path(d['full']))!=d['full_sha256'] or sha256(run/'pipeline-result.json')!=d['pipeline_sha256']:
            raise ValueError('核对期间原任务发生变化，未替换结果')
        # Backups are durable before any task artifact changes.
        names=['models/body.blend','pipeline-result.json','body-analysis.json','body-selection.json',
            'body-source-verification.json','body-decision.json','manual-body.json','manual-body.html','body-previews']
        backup=folder/'before';backup.mkdir()
        for name in names:
            src=run/name
            if src.is_dir():shutil.copytree(src,backup/name)
            elif src.is_file():
                dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
                if sha256(src)!=sha256(dest):raise ValueError('原结果备份核对失败：'+name)
        try:
            body=run/'models/body.blend';shutil.copy2(candidate,body)
            if sha256(body)!=sha256(candidate):raise ValueError('身体复制核对失败')
            for name in ('body-analysis.json','body-selection.json','body-source-verification.json','body-decision.json','manual-body.html'):
                shutil.copy2(folder/name,run/name)
            # Stage previews are complete; replace only these four view files and inspection.
            preview=run/'body-previews';preview.mkdir(exist_ok=True)
            for file in (folder/'body-previews').iterdir():
                if file.is_file():shutil.copy2(file,preview/file.name)
            manual={**outcome,'status':'passed','selection_method':'user_saved_deletion',
                'measurements':verified['measurements'],'removed':verified['removed'],
                'verification':str(folder/'verification.json'),'scope':verified['scope'],
                'full_sha256':d['full_sha256'],'body_sha256':sha256(body)}
            write_json(run/'manual-body.json',manual)
            result=read_json(run/'pipeline-result.json')
            result.update(body_status='available',body_completeness='verified_scope',
                body_reason=read_json(folder/'body-decision.json'),body_fingerprints=verified['fingerprints'],
                manual_body=manual,body_visual_review_status='user_selected_saved',game_compatibility_status='unverified')
            result['files']['body']={'path':str(body),'sha256':sha256(body),'size':body.stat().st_size}
            write_json(run/'pipeline-result.json',result)
        except Exception:
            for name in names:
                target=run/name;old=backup/name
                if old.is_dir():
                    for file in target.iterdir():
                        if file.is_file():file.unlink()
                    shutil.copytree(old,target,dirs_exist_ok=True)
                elif old.is_file():shutil.copy2(old,target)
                elif target.is_file():target.unlink()
                elif target.is_dir():
                    for file in target.iterdir():
                        if file.is_file():file.unlink()
            raise
        return finish('passed','已按保存的删减结果生成 body.blend；测量和核对记录已保存，可保存到素材库。',run=str(run))
    except Exception as error:
        return finish('failed','本次身体未生成：'+str(error)+'。编辑副本及日志已保留。')


class ManualBodyService:
    def __init__(self):self.thread=None;self.events=queue.Queue()
    @property
    def busy(self):return self.thread is not None and self.thread.is_alive()
    def start(self,run,blender):
        if self.busy:raise ValueError('已有手动删减窗口正在等待保存退出')
        guard=task_guard(run);guard.__enter__()
        try:session=prepare_session(run,blender)
        except BaseException:
            guard.__exit__(None,None,None);raise
        def work():
            try:
                script=resource_root()/'tools/mod-extractor/manual_body_blender.py'
                # This is an explicitly requested visible editor, separate from existing Blender instances.
                with (session.parent/'editor.log').open('wb') as log:
                    process=subprocess.Popen([blender,'--factory-startup','--disable-autoexec',
                        read_json(session)['working'],'--python',str(script),'--',str(session),'edit'],
                        stdout=log,stderr=subprocess.STDOUT)
                    code=process.wait()
                value=finish_session(session,code)
            except Exception as error:
                value={'status':'failed','message':str(error),'session':str(session)}
                write_json(session.parent/'outcome.json',value)
            finally:guard.__exit__(None,None,None)
            self.events.put({**value,'run':str(Path(run).resolve())})
        self.thread=threading.Thread(target=work,daemon=True)
        try:self.thread.start()
        except BaseException:
            guard.__exit__(None,None,None);raise
        return session
    def drain(self):
        events=[]
        while True:
            try:events.append(self.events.get_nowait())
            except queue.Empty:return events
