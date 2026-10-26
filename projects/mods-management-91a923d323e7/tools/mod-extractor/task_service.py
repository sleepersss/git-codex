"""One owned worker tree; structured events, persisted diagnostics."""
import subprocess,threading,queue,uuid,json,os
from pathlib import Path
from datetime import datetime,timezone
from app_paths import worker_command
LABELS={'prepare':'备份来源并准备环境','normalize':'整理模型组','reverse':'提取源缓冲区',
    'import':'保存 Mod 提取模型','islands':'检查表面分组','body':'保存已核对裸模',
    'body_abandoned':'已放弃裸模，只保留 Mod 提取模型','texcoord':'保留源属性','verify':'核对模型数据',
    'previews':'生成模型预览','body_analysis':'识别源身体并检查肢体连接','body_unverified':'身体分组或完整性待核对，完整 Mod 模型已保存'}

class TaskService:
    def __init__(self):
        self.events=queue.Queue();self.thread=None;self.process=None;self.task_id=None;self.cancelled=threading.Event();self.stop_lock=threading.Lock()
    @property
    def busy(self):return self.thread is not None and self.thread.is_alive()
    def publish(self,**event):
        value={'task_id':self.task_id,'at':datetime.now(timezone.utc).isoformat(),
               'stage':'task','status':'running','message':'','reason_code':'','artifacts':{}}
        value.update(event);self.events.put(value)
    def start(self,profile,source,config):
        if self.busy:raise ValueError('已有任务正在运行')
        self.task_id=uuid.uuid4().hex;self.cancelled.clear();self.process=None;self.run=None;self.tree_stopped=False
        from worker_tree import WorkerTree
        self.worker_tree=WorkerTree()
        folder=Path(config['work_root'])/'requests';folder.mkdir(parents=True,exist_ok=True)
        request=folder/(self.task_id+'.json')
        request.write_text(json.dumps({'profile':profile,'source':str(source),'config':config},ensure_ascii=False),encoding='utf-8')
        self.publish(stage='prepare',message=LABELS['prepare'])
        owned_tree=self.worker_tree
        def work():
            watcher=None;owned_process=None
            try:
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                with (folder/(self.task_id+'.log')).open('w',encoding='utf-8') as log:
                    if not self.worker_tree.handle:raise ValueError('无法隔离后台进程，任务未启动：'+self.worker_tree.error)
                    self.process=subprocess.Popen(worker_command(request),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                        text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONUTF8':'1'},creationflags=flags|self.worker_tree.creation_flags)
                    owned_process=self.process
                    self.worker_tree.attach_and_resume(self.process)
                    def watch_exit(process=owned_process,tree=owned_tree):
                        process.wait()
                        with self.stop_lock:
                            if not self.tree_stopped:self.tree_stopped=tree.stop_and_confirm()
                    # Observe exit even when a descendant keeps the stdout pipe open.
                    watcher=threading.Thread(target=watch_exit,daemon=True);watcher.start()
                    if self.cancelled.is_set():self._stop_process()
                    final=None
                    for line in self.process.stdout:
                        log.write(line);log.flush()
                        try:event=json.loads(line)
                        except (ValueError,TypeError):continue
                        if isinstance(event,dict) and event.get('kind')=='event':
                            if event.get('artifacts',{}).get('run'):self.run=Path(event['artifacts']['run'])
                            event.pop('kind');event.setdefault('artifacts',{})['log']=str(folder/(self.task_id+'.log'))
                            if event.get('status') in ('passed','failed'):final=event
                            else:self.publish(**event)
                    code=self.process.wait()
                    watcher.join()
                    self.process.stdout.close()
                    # taskkill can close stdout before it confirms descendant termination.
                    with self.stop_lock:
                        if not self.tree_stopped:self.tree_stopped=self.worker_tree.stop_and_confirm()
                    if self.cancelled.is_set():
                        if self.run:
                            from runner import read_json,write_json
                            path=self.run/'pipeline-result.json'
                            record=read_json(path) if path.exists() else {}
                            record.update(status='cancelled',error='用户取消任务；产物不可入库')
                            write_json(path,record)
                            self._cleanup(config)
                        self.publish(status='cancelled',message='任务已取消；未完成结果不会入库。')
                    else:
                        self._cleanup(config)
                        if final is None or (code!=0 and final.get('status')!='failed'):
                            self.publish(status='failed',message='处理停止，请查看本次日志。',reason_code='worker_failed',
                                         artifacts={'log':str(folder/(self.task_id+'.log'))})
                        else:self.publish(**final)
            except Exception as error:self.publish(status='failed',message=str(error),reason_code='launch_failed')
            finally:
                # The service cannot become idle until its watcher and descendants exit.
                with self.stop_lock:owned_tree.stop_and_confirm()
                if watcher:watcher.join()
                owned_tree.close()
                if owned_process and owned_process.stdout and not owned_process.stdout.closed:owned_process.stdout.close()
        self.thread=threading.Thread(target=work,daemon=True);self.thread.start();return self.task_id
    def _stop_process(self):
        with self.stop_lock:self._stop_process_locked()
    def _stop_process_locked(self):
        process=self.process
        if process is not None and process.poll() is None:
            if self.worker_tree.handle:
                self.tree_stopped=self.worker_tree.stop_and_confirm()
                if self.tree_stopped:return
            if os.name=='nt':
                result=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                # A termination command alone does not confirm the Job is empty.
                self.tree_stopped=self.worker_tree.stop_and_confirm() if self.worker_tree.handle else False
                if result.returncode and process.poll() is None:process.terminate()
            else:process.terminate()
    def _cleanup(self,config):
        if not self.run:return
        try:
            self.publish(stage='cleanup',message='清理本次临时文件；保留模型、报告和来源备份')
            from cleanup_service import cleanup_run
            if self.tree_stopped:report=cleanup_run(self.run,config['work_root'])
            else:
                from runner import write_json,now
                report={'at':now(),'status':'skipped','removed':[],'bytes_removed':0,'warnings':['无法确认后台子进程全部退出，临时文件已保留。'+self.worker_tree.error]}
                # The cleanup helper validates the task folder before any writes.
                cleanup_run(self.run,config['work_root'],processes_stopped=False,skip_reason=report['warnings'][0])
            if report['warnings']:
                self.publish(stage='cleanup',message='部分临时文件已保留，详情见清理记录。',artifacts={'cleanup':str(self.run/'cleanup-result.json')})
        except Exception as error:
            self.publish(stage='cleanup',message='临时文件清理未完成：'+str(error))
    def cancel(self,task_id):
        if task_id!=self.task_id:return
        self.cancelled.set();self._stop_process()
    def drain(self):
        rows=[]
        while True:
            try:rows.append(self.events.get_nowait())
            except queue.Empty:return rows
