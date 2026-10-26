"""Local extraction staging/engine runner. No Codex or network dependency."""
from pathlib import Path
import argparse,json,shutil,subprocess,sys,os,uuid,re
from app_paths import resource_root,resolve_paths
ROOT=resource_root()
sys.path.insert(0,str(ROOT/'model-library'))
from library import Library,read_json,write_json,sha256,inventory,now
from locking import locked

def prepare(name,source,game,ini,author=None,config=None):
    library_game={'WWMI':'WW','WW':'WW','HSR':'HSR','ZZZ':'ZZZ'}[game]
    game={'WW':'WWMI','HSR':'HSR','ZZZ':'ZZZ'}[library_game]
    source=Path(source).resolve(strict=True)
    if not source.is_dir():raise ValueError('This prototype accepts directories; archive support is planned')
    if not re.fullmatch(r'[a-z0-9_-]{1,40}',name):raise ValueError('Invalid job name')
    target_source_ini=(source/ini).resolve(strict=True)
    if not target_source_ini.is_relative_to(source) or not target_source_ini.is_file():raise ValueError('Main INI must be inside source folder')
    cfg=resolve_paths(config)
    if any(Path(cfg[key]).resolve().is_relative_to(source) for key in ('work_root','library_root')):
        raise ValueError('Output directories must not be inside the original Mod source')
    sword=Path(cfg['sword_root']).resolve(strict=True)
    blender=Path(cfg['blender']).resolve(strict=True)
    herta_parent=Path(cfg['herta_parent']).resolve(strict=True)
    assert (sword/'Plugins/3Dmigoto-Sword-Lv5.vmp.exe').is_file() and (herta_parent/'HertaBlender/__init__.py').is_file()
    work_root=Path(cfg['work_root']).resolve();work_root.mkdir(parents=True,exist_ok=True)
    run=work_root/('mod-extraction-'+name+'-'+now()[:10].replace('-','')+'-'+uuid.uuid4().hex[:8])
    if run.exists():raise ValueError('Output already exists')
    lib=Library(cfg['library_root'])
    with locked(lib):
        record=lib.source(source,library_game,author=author,license_note='未确认；仅本地研究，来源及作者声明原样保留')
    run.mkdir()
    shutil.copytree(lib.inside(record['payload']),run/'input')
    # Preserve a complete runtime, but do not clone old logs or output collections.
    shutil.copytree(sword,run/'sword',ignore=shutil.ignore_patterns('Logs','Reversed'))
    for p in ('Logs','Reversed'):(run/'sword'/p).mkdir(exist_ok=True)
    target_ini=run/'input'/ini
    if not target_ini.is_file():raise ValueError('Main INI missing')
    settings=read_json(run/'sword/Configs/Settings.json')
    settings.update(GameName=game,AutotOpenReversedFolder=False)
    write_json(run/'sword/Configs/Settings.json',settings)
    write_json(run/'sword/Configs/RunInput.json',{'GameName':game,'ReverseFilePath':str(target_ini),'RunCommand':'ReverseSingleLv5'})
    (run/'sword/Configs/RunResult.json').unlink(missing_ok=True)
    job={'name':name,'game':game,'library_game':library_game,'source_id':record['id'],'source':str(source),'input_kind':'directory' if source.is_dir() else 'file',
         'main_ini':str(target_ini),'source_manifest_sha256':record['manifest_sha256'],
         'source_manifest':record['manifest'],
         'sword':str(run/'sword'),'blender':str(blender),
         'herta_parent':str(herta_parent),'library_root':str(lib.root),'created_at':now(),'status':'prepared'}
    write_json(run/'job.json',job)
    return {'run':str(run),'source_id':record['id'],'source_files':len(record['manifest'])}

def reverse(run,ini=None,timeout=90):
    run=Path(run).resolve(strict=True);job=read_json(run/'job.json');tool=Path(job['sword'])
    if ini:
        ini=Path(ini).resolve(strict=True)
        if not ini.is_relative_to(run/'input'):raise ValueError('INI must be inside input copy')
        write_json(tool/'Configs/RunInput.json',{'GameName':job['game'],'ReverseFilePath':str(ini),'RunCommand':'ReverseSingleLv5'})
    (tool/'Configs/RunResult.json').unlink(missing_ok=True)
    current_ini=Path(read_json(tool/'Configs/RunInput.json')['ReverseFilePath'])
    output_root=current_ini.parent.with_name(current_ini.parent.name+'-Reverse')
    previous={str(p):(p.stat().st_mtime_ns,p.stat().st_size) for p in output_root.rglob('*') if p.is_file()} if output_root.exists() else {}
    started=now();stamp=started.replace(':','-')
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    with (run/('sword-'+stamp+'.stdout.log')).open('wb') as out,(run/('sword-'+stamp+'.stderr.log')).open('wb') as err:
        process=subprocess.Popen([str(tool/'Plugins/3Dmigoto-Sword-Lv5.vmp.exe')],cwd=tool,
            stdin=subprocess.DEVNULL,stdout=out,stderr=err,startupinfo=startup)
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:process.kill();process.wait();code='timeout'
    try:result=read_json(tool/'Configs/RunResult.json')
    except (OSError,ValueError):result={'result':'missing_or_invalid_result'}
    # Only newly emitted buffers count as extraction output; exit 0 alone is insufficient.
    outputs=[p for p in output_root.rglob('*.fmt') if previous.get(str(p))!=(p.stat().st_mtime_ns,p.stat().st_size)
             and all(p.with_suffix(ext).is_file() and p.with_suffix(ext).stat().st_size>0 for ext in ('.ib','.vb'))]
    report={'at':now(),'exit':code,'engine_result':result,'fmt_count':len(outputs),
            'input_ini':str(current_ini),'fmt_files':[str(p.relative_to(run)) for p in outputs],
            'status':'buffers_generated' if code==0 and outputs else 'no_usable_buffers'}
    write_json(run/'reverse-result.json',report)
    job['status']=report['status'];write_json(run/'job.json',job)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('name');p.add_argument('source');p.add_argument('--game',required=True)
    p.add_argument('--ini',required=True);p.add_argument('--author');p.add_argument('--config')
    p=sub.add_parser('reverse');p.add_argument('run');p.add_argument('--ini')
    args=vars(parser.parse_args());command=args.pop('command')
    result=prepare(**args) if command=='prepare' else reverse(**args)
    print(json.dumps(result,ensure_ascii=False,indent=2))
