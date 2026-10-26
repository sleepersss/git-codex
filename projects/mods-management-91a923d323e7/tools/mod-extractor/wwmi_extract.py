"""Complete WWMI extraction: Sword reverse, every draw, on-disk shapekeys, then body."""
from pathlib import Path
import json,subprocess
from runner import reverse,read_json,write_json,sha256,now
from app_paths import resource_root
from body_policy import evaluate_body,output_roles
from wwmi_draw_map import parse_component_draws,expected_fmt_count,select_reverse_layout


def uses_complete_wwmi(profile,game):
    if profile in ('denia','iuno'):return False
    return str(game).upper() in ('WW','WWMI')


def recorded_model_files(run,roles):
    """Hash files after every Blender save (body, texcoord, verify)."""
    run=Path(run)
    return {role:{'path':str(run/'models'/f'{role}.blend'),'sha256':sha256(run/'models'/f'{role}.blend')} for role in roles}


def execute_wwmi(run,emit=lambda s:None):
    run=Path(run).resolve(strict=True);job=read_json(run/'job.json')
    expected_ini=Path(job['main_ini']).resolve(strict=True)
    if not expected_ini.is_relative_to(run/'input'):raise ValueError('Main INI must be inside the isolated input copy')
    if (run/'models/full.blend').exists():raise ValueError('Results already exist; use a new job or --rerun for this work copy')
    for row in job['source_manifest']:
        file=(run/'input'/row['path']).resolve(strict=True)
        if not file.is_relative_to(run/'input') or file.stat().st_size!=row['size'] or sha256(file)!=row['sha256']:
            raise ValueError('来源副本发生变化：'+row['path'])
    components=parse_component_draws(expected_ini)
    expected=expected_fmt_count(components)
    if expected<=0:raise ValueError('配置没有可提取的 TextureOverrideComponent 绘制范围')
    decision=evaluate_body('auto',{})
    write_json(run/'body-decision.json',decision)
    result={'at':now(),'profile':'auto-wwmi','status':'running','stages':[],
            'title':job.get('character'),'body_status':'unverified','body_reason':decision,'full_status':'pending'}
    write_json(run/'pipeline-result.json',result)
    here=resource_root()/'tools/mod-extractor'
    def stage(label,script,timeout=300):
        command=[job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
                 '--python',str(here/script),'--',str(run)]
        with (run/(label+'.log')).open('wb') as log:
            completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode:raise RuntimeError(label+' failed; inspect '+str(run/(label+'.log')))
        result['stages'].append(label);write_json(run/'pipeline-result.json',result)
        emit(label)
    emit('reverse')
    report=reverse(run,expected_ini,timeout=300)
    result['engine_runs']=[report]
    if report['status']!='buffers_generated':
        raise RuntimeError('Sword 未生成完整缓冲区：'+json.dumps(report,ensure_ascii=False))
    reverse_root=expected_ini.parent.with_name(expected_ini.parent.name+'-Reverse')
    layout=select_reverse_layout(reverse_root,expected)
    write_json(run/'wwmi-draw-map.json',{'layout':str(layout.relative_to(run)),'expected_fmt':expected,
        'components':{cid:[{k:v for k,v in row.items() if k!='conditions'}|{ 'conditions':row['conditions']} for row in rows]
                      for cid,rows in components.items()}})
    if report['fmt_count']<expected:
        raise RuntimeError('Sword 输出组数少于源绘制范围：%s < %s'%(report['fmt_count'],expected))
    stage('import','import_wwmi.py',timeout=900)
    imported=read_json(run/'import-verification.json')
    if imported.get('status')!='full_imported' or len(imported.get('objects',[]))!=expected:
        raise RuntimeError('导入对象数量与源绘制范围不一致：%s != %s'%(len(imported.get('objects',[])),expected))
    from body_pipeline import extract_source_body
    outcome=extract_source_body(run,emit)
    result.update(outcome)
    decision=read_json(run/'body-decision.json');roles=output_roles(run,decision)
    stage('texcoord','retain_texcoord.py')
    stage('verify','verify_wwmi.py')
    verification=read_json(run/'data-preservation-verification.json')
    if verification.get('status')!='passed':raise RuntimeError('模型保存后核对失败')
    inspector=resource_root()/'model-library/inspect_blend.py'
    emit('previews')
    for role in roles:
        folder=run/(role+'-previews')
        cmd=[job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
             str(run/'models'/f'{role}.blend'),'--python',str(inspector),'--',str(folder),'--previews']
        with (run/(role+'-preview.log')).open('wb') as log:
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180,check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if not all((folder/(view+'.png')).is_file() for view in ('front','back','side','three_quarter')):
            raise RuntimeError('预览生成未完成：'+role)
    shapekeys=imported.get('shapekeys',{})
    result.pop('body_file',None)
    files=recorded_model_files(run,roles)
    result.update(status='passed',full_status='verified',files=files,verification=imported,
        body_completeness='verified_scope' if decision['status']=='eligible' else 'none',
        shapekeys=shapekeys,source_draw_coverage={'source_numeric_draws':expected,'covered':len(imported['objects']),
            'scope':'all TextureOverrideComponent drawindexed ranges'},
        limitations=['静态工程模型：默认显示源配置的一套切换状态；其他源网格保留但隐藏。',
                     '已从磁盘 ShapeKey 表还原 128 通道偏移；未执行来源 HLSL 动画或游戏骨架。',
                     '身体检查采用直立源姿态和明确源部件标签；输出范围不含头发和头部。'],
        library_import='separate explicit step; existing records untouched',
        preview_status='ready',game_compatibility_status='unverified')
    if shapekeys.get('status')!='decoded':
        result['limitations'][1]='来源没有可解码的 ShapeKeyOffset 表；已保存基础网格与绘制范围，动态通道记为未还原。'
    from body_review import body_report_artifact
    result.update(body_report_artifact(run))
    write_json(run/'pipeline-result.json',result)
    return result
