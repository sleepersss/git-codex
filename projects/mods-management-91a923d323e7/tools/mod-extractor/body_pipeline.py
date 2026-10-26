"""Body outcome is decided after actual source mesh inspection, not from empty evidence."""
import subprocess
from pathlib import Path
from runner import read_json,write_json,sha256
from app_paths import resource_root

def extract_source_body(run,emit=lambda s:None):
    """Body errors are recorded without invalidating the already extracted full model."""
    try:result=_extract_source_body(run,emit)
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        run=Path(run)
        body=run/'models/body.blend'
        if body.exists():
            # A failed candidate is retained for diagnosis, never exposed as available.
            import uuid
            rejected=run/'rejected';rejected.mkdir(exist_ok=True)
            body.rename(rejected/('unverified-'+uuid.uuid4().hex[:8]+'.blend'))
        decision={'status':'unverified','reason_code':'body_analysis_failed','missing_parts':[],
            'message':'身体检查未完成，完整 Mod 模型已保留。详情见身体检查日志。','error':str(error)}
        write_json(run/'body-decision.json',decision);emit('body_unverified')
        result={'body_status':'unverified','body_reason':decision,'body_completeness':'none'}
    from body_review import body_report_artifact
    result.update(body_report_artifact(run))
    result.update(body_visual_review_status='not_run',game_compatibility_status='unverified')
    return result

def _extract_source_body(run,emit):
    run=Path(run);job=read_json(run/'job.json');emit('body_analysis')
    script=resource_root()/'tools/mod-extractor/analyze_source_body.py'
    with (run/'body-analysis.log').open('w',encoding='utf-8') as log:
        p=subprocess.run([job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script),'--',str(run)],stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:raise ValueError('身体检查未完成，完整 Mod 模型已保留。记录：'+str(run/'body-analysis.log'))
    decision=read_json(run/'body-decision.json')
    status={'eligible':'available','abandoned':'abandoned','unverified':'unverified'}[decision['status']]
    result={'body_status':status,'body_reason':decision,'body_completeness':'verified_scope' if status=='available' else 'none'}
    if status=='available':
        body=run/'models/body.blend';verification=read_json(run/'body-selection.json')
        if not verification['saved_file_reopened'] or not verification['source_geometry_unchanged']:raise ValueError('身体保存后核对失败')
        verifier=resource_root()/'tools/mod-extractor/verify_body_subset.py'
        with (run/'body-source-verification.log').open('w',encoding='utf-8') as log:
            subprocess.run([job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(verifier),'--',str(run)],stdout=log,stderr=subprocess.STDOUT,timeout=300,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if read_json(run/'body-source-verification.json')['status']!='passed':raise ValueError('身体源数据核对失败')
        result['body_file']={'path':str(body),'sha256':sha256(body)};result['body_fingerprints']=verification['fingerprints'];emit('body')
    else:emit('body_abandoned' if status=='abandoned' else 'body_unverified')
    return result
