"""Direct static indexed-buffer extraction; never execute Mod commands."""
from pathlib import Path
import json,subprocess,re
from runner import read_json,write_json,sha256
from app_paths import resource_root
from discovery import inspect_ini
from body_policy import evaluate_body
from body_selection import draw_metadata

def plan_meshes(root,ini):
    from static_plan import plan_static
    return plan_static(root,ini)

def source_draw_coverage(ini,plans):
    from static_plan import command_sections
    represented={(p['section'].casefold(),p['count'],p['start'],p['base']) for p in plans}
    source=[]
    for section,nodes in command_sections(ini).items():
        for key,value,label in nodes:
            if key!='drawindexed':continue
            match=re.fullmatch(r'(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)',value)
            if match:source.append((section,*map(int,match.groups())))
    return {'source_numeric_draws':len(source),'covered':sum(k in represented for k in source),
        'scope':'numeric source draw ranges only; runtime states, deformation and skeleton not verified'}

def execute_generic(run,emit=lambda s:None):
    run=Path(run);job=read_json(run/'job.json');root=run/'input'
    emit('verify')
    for row in job['source_manifest']:
        if sha256(root/row['path'])!=row['sha256']:raise ValueError('来源副本发生变化：'+row['path'])
    plans=plan_meshes(root,job['main_ini'])
    for plan in plans:plan['game']=job.get('library_game',job['game'])
    write_json(run/'mesh-plan.json',plans)
    decision=evaluate_body('auto',{});write_json(run/'body-decision.json',decision)
    emit('import');script=resource_root()/'tools/mod-extractor/import_generic.py'
    with (run/'generic-import.log').open('w',encoding='utf-8') as log:
        p=subprocess.run([job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script),'--',str(run)],stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode or not (run/'generic-verification.json').exists():
        lines=(run/'generic-import.log').read_text(encoding='utf-8',errors='replace').splitlines()
        detail=next((line for line in reversed(lines) if 'Error:' in line),'模型读取未完成')
        raise ValueError(detail+'；详细记录：'+str(run/'generic-import.log'))
    verification=read_json(run/'generic-verification.json')
    if verification['status']!='passed':raise ValueError('模型保存后核对失败')
    runtime_base=any(p.get('runtime_position',{}).get('status')=='source_base_only' for p in plans)
    if runtime_base:
        decision={'status':'unverified','reason_code':'runtime_geometry_unverified','missing_parts':[],
            'message':'已保存源基础网格；动态形态与骨架尚未还原，不能作为完整可复刻 Mod 或已验证裸模。'}
        write_json(run/'body-decision.json',decision)
        write_json(run/'body-candidates.json',{'status':'unresolved','selected':[],'alternatives':[],
            'parts':[{'name':'%03d_%s'%(i,p['section']),'label':p.get('label',''),'conditions':p.get('conditions',[])} for i,p in enumerate(plans)],
            'unresolved':['runtime_shape_offsets'],'excluded':[],'states_evaluated':0})
        body_result={'body_status':'unverified','body_reason':decision,'body_completeness':'none',
            'body_visual_review_status':'not_run','game_compatibility_status':'unverified'}
        emit('body_unverified')
    else:
        from body_pipeline import extract_source_body
        body_result=extract_source_body(run,emit)
    full=run/'models/full.blend'
    result={'status':'passed','profile':'auto','title':job['character'],'full_status':'partial' if runtime_base else 'verified',**body_result,
        'files':{'full':{'path':str(full),'sha256':sha256(full)}},'verification':verification,
        'limitations':['静态工程模型：未恢复游戏骨骼、材质着色器或动态滑条。','身体检查采用直立源姿态和明确源部件标签；输出范围不含头发和头部。']}
    if body_result.get('body_file'):result['files']['body']=result.pop('body_file')
    if runtime_base:
        result.update(geometry_scope='source_base_meshes',runtime_geometry_status='unverified',
            source_draw_coverage=source_draw_coverage(job['main_ini'],plans))
        write_json(run/'source-draw-coverage.json',result['source_draw_coverage'])
    unresolved=sum(p.get('default_display_status')=='unresolved' for p in plans)
    result['default_display']={'status':'unresolved' if unresolved else 'resolved','unresolved_draws':unresolved}
    if unresolved:result['limitations'].append('部分源条件依赖未知运行时值；这些备选网格保留并隐藏，默认显示未确定。请在工程中核对后选择。')
    emit('previews');inspector=resource_root()/'model-library/inspect_blend.py';preview_errors=[]
    no_visible_base=runtime_base and not any(p.get('visible_by_default',True) for p in plans)
    for role in (() if no_visible_base else result['files']):
        try:
            folder=run/(role+'-previews')
            with (run/(role+'-previews.log')).open('w',encoding='utf-8') as log:
                p=subprocess.run([job['blender'],'--background','--factory-startup','--disable-autoexec',str(run/'models'/(role+'.blend')),'--python-exit-code','1','--python',str(inspector),'--',str(folder),'--previews','--preview-only'],stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            if p.returncode or not all((folder/(view+'.png')).is_file() for view in ('front','back','side','three_quarter')):raise ValueError('预览生成未完成：'+role)
        except (OSError,ValueError,subprocess.SubprocessError) as error:preview_errors.append(str(error))
    result.update(preview_status='ready' if not preview_errors else 'unavailable',preview_errors=preview_errors)
    if no_visible_base:
        result.update(preview_status='not_run',preview_errors=['源默认显示条件尚未确定；未生成空白或强行叠加变体的预览。'])
    result['limitations'][0]='静态工程模型：默认显示源配置的一套切换状态；其他源网格保留但隐藏。未恢复游戏骨骼、材质着色器或动态滑条。'
    if runtime_base:result['limitations'][0]='仅保存已核对来源的基础网格与绘制范围；动态 ShapeKey、变形、权重重映射和游戏状态尚未还原，不代表完整复刻成功。'
    from body_review import body_report_artifact
    result.update(body_report_artifact(run))
    write_json(run/'pipeline-result.json',result);return result
