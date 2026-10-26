"""Standalone desktop entry; workers dispatch without importing Qt."""
import sys,json,traceback
from pathlib import Path

def worker(request_path):
    from runner import prepare,write_json
    from extract import execute,PROFILES
    from task_service import LABELS
    request_path=Path(request_path);request=json.loads(request_path.read_text(encoding='utf-8'));run=None
    # ASCII JSON escapes keep Chinese intact through frozen Windows console pipes.
    def event(**value):print(json.dumps({'kind':'event',**value},ensure_ascii=True),flush=True)
    try:
        profile=request['profile'];config_path=request_path.with_suffix('.config.json');write_json(config_path,request['config'])
        event(stage='prepare',message=LABELS['prepare'])
        if isinstance(profile,dict):
            from discovery import discover_mod
            from generic_extract import execute_generic
            import hashlib
            detected=discover_mod(request['source'],profile.get('game'))
            if not detected['supported']:raise ValueError(detected['message'])
            ini=profile.get('ini') or detected['selected_ini']
            if ini not in [c['ini'] for c in detected['candidates'] if c['valid']]:raise ValueError('所选配置无法读取模型资源')
            name='auto-'+hashlib.sha256(str(request['source']).encode()).hexdigest()[:12]
            run=Path(prepare(name,request['source'],detected['game'],ini,config=config_path)['run'])
            job=json.loads((run/'job.json').read_text(encoding='utf-8'));job.update(character=detected['title'],configuration=ini);write_json(run/'job.json',job)
            matched=next((k for k,v in PROFILES.items() if v['manifest']==job['source_manifest_sha256'] and v['ini']==ini),None)
            if matched:
                job['name']=matched;job.pop('configuration',None);write_json(run/'job.json',job);profile=matched
        else:
            run=Path(prepare(profile,request['source'],'WW',PROFILES[profile]['ini'],PROFILES[profile]['author'],config_path)['run'])
        event(stage='prepare',message='来源备份已核对',artifacts={'run':str(run)})
        emit=lambda stage:event(stage=stage,message=LABELS.get(stage,stage))
        if isinstance(profile,dict):
            from wwmi_extract import execute_wwmi,uses_complete_wwmi
            game=job.get('library_game') or job.get('game')
            result=execute_wwmi(run,emit) if uses_complete_wwmi(profile,game) else execute_generic(run,emit)
        else:
            result=execute(run,profile,emit=emit)
        message={'available':'Mod 模型与源裸模均已保存并核对。','abandoned':'Mod 模型已保存；肢体有缺口，裸模已放弃。','unverified':'Mod 模型已保存；身体分组或完整性待核对，请查看任务报告。'}[result['body_status']]
        if result.get('full_status')=='partial':message='源基础网格已保存；动态形态尚未还原，不能直接复刻原 Mod。'
        event(stage='task',status='passed',message=message,
            artifacts={'run':str(run),'body_status':result['body_status'],'full_status':result.get('full_status'),'result':str(run/'pipeline-result.json')})
        return 0
    except Exception as error:
        if run:
            write_json(run/'pipeline-result.json',{'status':'failed','full_status':'failed','body_status':'abandoned','error':str(error),'profile':'auto' if isinstance(request['profile'],dict) else request['profile']})
        traceback.print_exc();event(stage='task',status='failed',message=str(error),reason_code='extraction_failed',artifacts={'run':str(run) if run else ''});return 1

if __name__=='__main__' and '--worker-task' in sys.argv:
    sys.exit(worker(sys.argv[sys.argv.index('--worker-task')+1]))
if __name__=='__main__' and '--script-worker' in sys.argv:
    import runpy
    i=sys.argv.index('--script-worker');script=sys.argv[i+1];sys.argv=[script,*sys.argv[i+2:]]
    runpy.run_path(script,run_name='__main__');sys.exit(0)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontDatabase
from app_paths import resolve_paths
from task_service import TaskService
from ui_pages import MainWindow

def main():
    app=QApplication(sys.argv);app.setApplicationName('Mod 素材提取工具')
    # Register installed CJK fonts explicitly; offscreen QA otherwise has no Windows font fallback.
    for filename in ('msyh.ttc','msyhbd.ttc','simhei.ttf'):
        path=Path('C:/Windows/Fonts')/filename
        if path.is_file():QFontDatabase.addApplicationFont(str(path))
    family=next((f for f in ('Microsoft YaHei UI','Microsoft YaHei','SimHei') if f in QFontDatabase.families()),app.font().family())
    app.setFont(QFont(family,11))
    config=resolve_paths();window=MainWindow(TaskService(),Path(config['library_root']),config);window.show()
    if '--smoke-ui' in sys.argv:
        from PySide6.QtCore import QTimer
        def capture():
            dest=Path(sys.argv[sys.argv.index('--smoke-ui')+1]);dest.parent.mkdir(parents=True,exist_ok=True);window.grab().save(str(dest))
            print(json.dumps({'screenshot':str(dest),'dpr':window.devicePixelRatioF(),'size':[window.width(),window.height()]},ensure_ascii=False),flush=True);app.quit()
        QTimer.singleShot(700,capture)
    if '--smoke-run' in sys.argv or '--smoke-source' in sys.argv:
        from PySide6.QtCore import QTimer
        import time
        option='--smoke-source' if '--smoke-source' in sys.argv else '--smoke-run'
        i=sys.argv.index(option);profile=sys.argv[i+1];report=Path(sys.argv[i+2]);started=time.monotonic()
        if option=='--smoke-source':window.source.setText(profile)
        else:
            from ui_pages import SAMPLES
            window.source.setText(SAMPLES[profile][1])
        def begin():
            if not window.start_button.isEnabled():
                report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps({'status':'failed','error':window.ready_label.text()},ensure_ascii=False),encoding='utf-8');app.exit(1)
            else:window.start_button.click()
        def finish():
            if window.service.busy and time.monotonic()-started<600:return
            if window.service.busy:window.service.cancel(window.service.task_id);return
            window.poll();value={'status':'failed','error':'Task did not produce a verified result'}
            if window.run and (window.run/'pipeline-result.json').exists():value=json.loads((window.run/'pipeline-result.json').read_text(encoding='utf-8'));value['run']=str(window.run)
            report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            window.grab().save(str(report.with_suffix('.png')));app.exit(0 if value['status']=='passed' else 1)
        test_timer=QTimer(window);test_timer.timeout.connect(finish);test_timer.start(500);window.test_timer=test_timer
        QTimer.singleShot(100,begin)
    return app.exec()

if __name__=='__main__':sys.exit(main())
