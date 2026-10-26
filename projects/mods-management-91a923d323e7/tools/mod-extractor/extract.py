"""Offline extraction prototype for two manifest-pinned regression samples."""
from pathlib import Path
import argparse,json,subprocess,sys,hashlib
from runner import prepare,reverse,read_json,write_json,sha256,now
from body_policy import evaluate_body,output_roles
from app_paths import resource_root
HERE=resource_root()/'tools/mod-extractor' if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
PROFILES={
    'denia':{'manifest':'560e47e21f22dcb41431b0ac9a698daef940e1fff399b5296c84290f30c735d3','ini':'Denia - GUI & OG & Maid & Bondage V1.0 [Veloria Lab]/mod.ini','author':'VeloriaLab'},
    'iuno':{'manifest':'7090efaa469aba02f0135127ff12f020c45c7db43eba2b8ad1dcf7d2a4639eaf','ini':'mod.ini','author':'weiwuxc888'}
}
def execute(run,profile,rerun=False,emit=None):
    run=Path(run).resolve(strict=True);job=read_json(run/'job.json')
    if job['name']!=profile or job['source_manifest_sha256']!=PROFILES[profile]['manifest']:
        raise ValueError('This input differs from the reviewed sample. A new source profile and manual review are required.')
    expected_ini=(run/'input'/PROFILES[profile]['ini']).resolve(strict=True)
    if Path(job['main_ini']).resolve()!=expected_ini or not Path(job['sword']).resolve().is_relative_to(run):
        raise ValueError('Job paths are outside the isolated copy')
    manifest=job.get('source_manifest')
    if manifest is None:
        from runner import ROOT,Library
        _,record=Library(ROOT/'model-library').find(job['source_id'],source=True)
        manifest=record['manifest']
    actual_manifest=hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if actual_manifest!=PROFILES[profile]['manifest']:raise ValueError('Source manifest itself failed hash verification')
    for row in manifest:
        file=(run/'input'/row['path']).resolve(strict=True)
        if not file.is_relative_to(run/'input') or file.stat().st_size!=row['size'] or sha256(file)!=row['sha256']:
            raise ValueError('Input snapshot failed source hash check: '+row['path'])
    if (run/'models/full.blend').exists() and not rerun:raise ValueError('Results already exist; use a new job or --rerun for this work copy')
    decision=evaluate_body(profile,{})
    roles=output_roles(run,decision)
    write_json(run/'body-decision.json',decision)
    result={'at':now(),'profile':profile,'status':'running','stages':[],
            'body_status':'available' if decision['status']=='eligible' else 'unverified',
            'body_reason':decision,'full_status':'pending'};write_json(run/'pipeline-result.json',result)
    def stage(label,script,blender=True):
        command=([job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(HERE/script),'--',str(run)]
                 if blender else ([str(Path(sys.executable).with_name('ModExtractorWorker.exe')),'--script-worker',str(HERE/script),str(run)]
                    if getattr(sys,'frozen',False) else [sys.executable,str(HERE/script),str(run)]))
        with (run/(label+'.log')).open('wb') as log:
            completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        if completed.returncode:raise RuntimeError(label+' failed; inspect '+str(run/(label+'.log')))
        result['stages'].append(label);write_json(run/'pipeline-result.json',result)
        print(label,flush=True)
        if emit:emit(label)
    try:
        if profile=='denia':
            stage('normalize','normalize_denia.py',False)
            inis=[run/'input'/('normalized-'+g)/'mod.ini' for g in ('ib0','ib1','ib2')]
        else:inis=[Path(job['main_ini'])]
        engine_results=[]
        for ini in inis:
            if emit:emit('reverse')
            report=reverse(run,ini)
            engine_results.append(report)
            if report['status']!='buffers_generated':raise RuntimeError('No newly generated complete buffer triplets: '+str(ini))
        result['engine_runs']=engine_results
        stage('import','import_wwmi.py')
        if profile=='iuno':stage('islands','islands.py')
        from body_pipeline import extract_source_body
        outcome=extract_source_body(run,emit or (lambda s:None));result.update(outcome)
        decision=read_json(run/'body-decision.json');roles=output_roles(run,decision)
        stage('texcoord','retain_texcoord.py');stage('verify','verify_wwmi.py')
        assert read_json(run/'data-preservation-verification.json')['status']=='passed'
        from app_paths import resource_root
        inspector=resource_root()/'model-library/inspect_blend.py'
        for role in roles:
            if emit:emit('previews')
            cmd=[job['blender'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',str(run/'models'/f'{role}.blend'),
                 '--python',str(inspector),'--',str(run/(role+'-previews')),'--previews']
            with (run/(role+'-preview.log')).open('wb') as log:
                subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=120,check=True)
        result.pop('body_file',None)
        result.update(status='passed',full_status='verified',files={r:{'path':str(run/'models'/f'{r}.blend'),'sha256':sha256(run/'models'/f'{r}.blend')} for r in roles},
            body_completeness='verified_scope' if decision['status']=='eligible' else 'none',
            library_import='separate explicit step; existing records untouched')
        from body_review import body_report_artifact
        result.update(body_report_artifact(run))
        write_json(run/'pipeline-result.json',result);print(json.dumps(result['files'],ensure_ascii=False,indent=2));return result
    except Exception as error:
        result.update(status='failed',error=str(error));write_json(run/'pipeline-result.json',result);raise
if __name__=='__main__':
    p=argparse.ArgumentParser(description='Local offline prototype; only the two reviewed source manifests are supported')
    p.add_argument('--profile',choices=PROFILES,required=True);p.add_argument('--job');p.add_argument('--source');p.add_argument('--config');p.add_argument('--rerun',action='store_true')
    a=p.parse_args()
    if bool(a.job)==bool(a.source):p.error('Specify exactly one of --job and --source')
    run=a.job or prepare(a.profile,a.source,'WW',PROFILES[a.profile]['ini'],PROFILES[a.profile]['author'],a.config)['run']
    print('JOB_DIR='+str(Path(run).resolve()),flush=True)
    execute(run,a.profile,a.rerun)
