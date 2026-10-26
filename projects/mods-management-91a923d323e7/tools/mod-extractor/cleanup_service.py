"""Remove only owned disposable copies after worker processes have exited."""
from pathlib import Path
import re,shutil,os,stat
from runner import read_json,write_json,inventory,sha256,now

def _linked(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())

def _ordinary_tree(path):
    if _linked(path):raise ValueError('链接目录不参与清理：'+str(path))
    from library import safe_files
    return safe_files(path)

def cleanup_run(run,work_root,processes_stopped=True,skip_reason='后台进程尚未确认退出'):
    """Caller must wait for the worker tree to exit; no active-task sweeping."""
    run=Path(run);work=Path(work_root).resolve()
    report={'at':now(),'status':'skipped','removed':[],'bytes_removed':0,'warnings':[]}
    try:
        if _linked(run) or run.resolve().parent!=work or not re.fullmatch(r'mod-extraction-[a-z0-9_-]+-\d{8}-[0-9a-f]{8}',run.name):
            raise ValueError('任务目录不在指定工作区直属目录')
        run=run.resolve(strict=True)
        job=read_json(run/'job.json');result=read_json(run/'pipeline-result.json')
        if not processes_stopped:raise ValueError(skip_reason)
        if result.get('status') not in ('passed','failed','cancelled'):raise ValueError('任务未结束')
        source=Path(job['source']).resolve()
        if run==source or run.is_relative_to(source) or source.is_relative_to(run):raise ValueError('任务目录与原 Mod 重叠')
        library_root=Path(job['library_root']).resolve()
        if library_root==run or library_root.is_relative_to(run) or run.is_relative_to(library_root):raise ValueError('任务目录与永久素材库重叠')
        outputs=[]
        for entry in result.get('files',{}).values():
            p=Path(entry['path']).resolve(strict=True)
            if not p.is_relative_to(run) or sha256(p)!=entry['sha256']:raise ValueError('结果路径或哈希变化，保留全部文件')
            outputs.append(p)
        report['status']='cleaned'
        targets=[run/'sword']
        ini_parent=Path(job['main_ini']).parent
        reverse=ini_parent.with_name(ini_parent.name+'-Reverse')
        input_dir=run/'input'
        if input_dir.exists() or _linked(input_dir) or reverse.exists():
            try:
                if input_dir.exists() or _linked(input_dir):_ordinary_tree(input_dir)
                lib=Path(job['library_root']).resolve(strict=True)
                game=job['library_game'];ident=job['source_id']
                if game not in ('WW','HSR','ZZZ') or not re.fullmatch('SRC-'+game+r'-\d{6}',ident):raise ValueError('来源编号无效')
                metadata=lib/'sources'/game/ident/'metadata.json'
                record=read_json(metadata);payload=lib/record['payload']
                if payload.resolve()!=metadata.parent/'payload' or not payload.resolve().is_relative_to(lib):raise ValueError('来源备份路径无效')
                _ordinary_tree(payload)
                manifest,digest=inventory(payload)
                if not record.get('backup_verified') or digest!=job['source_manifest_sha256'] or manifest!=job['source_manifest'] or digest!=record['manifest_sha256']:
                    raise ValueError('永久来源备份核对失败，保留输入副本')
                # Save small source configs for readable historical diagnostics.
                archive=run/'source-config'
                if archive.exists():_ordinary_tree(archive)
                for ini in input_dir.rglob('*.ini'):
                    relative=ini.relative_to(input_dir);dest=archive/relative
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    if dest.exists() and sha256(dest)!=sha256(ini):raise ValueError('已有配置归档不同，保留输入副本')
                    if not dest.exists():shutil.copy2(ini,dest)
                report['source_backup']=str(payload)
                if input_dir.exists():targets.append(input_dir)
                if reverse.parent==run and reverse.name=='input-Reverse':targets.append(reverse)
            except (OSError,ValueError,KeyError) as error:
                report['warnings'].append(str(error));report['status']='partial'
        for target in targets:
            if not target.exists() and not _linked(target):continue
            try:
                if target.resolve().parent!=run or target.name not in ('input','sword','input-Reverse'):raise ValueError('清理目标不在允许范围')
                if any(p==target.resolve() or p.is_relative_to(target.resolve()) for p in outputs):raise ValueError('结果文件仍引用清理目标：'+target.name)
                files=_ordinary_tree(target);size=sum(p.stat().st_size for p in files)
                if target.name=='sword':
                    diagnostics=run/'engine-diagnostics'
                    if diagnostics.exists():_ordinary_tree(diagnostics)
                    for p in files:
                        rel=p.relative_to(target)
                        if rel.parts[0]!='Logs' and p.suffix.lower() not in ('.log','.json','.txt','.ini'):continue
                        dest=diagnostics/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                        if dest.exists() and sha256(dest)!=sha256(p):raise ValueError('已有引擎记录不同，保留引擎目录')
                        if not dest.exists():shutil.copy2(p,dest)
                        if sha256(dest)!=sha256(p):raise ValueError('引擎记录归档核对失败')
                def clear_copy_readonly(function,path,error):
                    p=Path(path)
                    if (os.name!='nt' or not isinstance(error,PermissionError) or _linked(p)
                        or not p.resolve().is_relative_to(target.resolve())
                        or not p.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):raise error
                    # Windows chmod changes only this disposable copy's read-only
                    # attribute; it does not alter ACLs or original tool files.
                    p.chmod(stat.S_IWRITE);function(path)
                shutil.rmtree(target,onexc=clear_copy_readonly)
                report['removed'].append(target.name);report['bytes_removed']+=size
            except (OSError,ValueError) as error:
                report['warnings'].append(str(error));report['status']='partial'
    except (OSError,ValueError,KeyError,TypeError) as error:
        report['warnings'].append(str(error))
    # Only write reports inside a validated task, never an arbitrary user path.
    if run.is_dir() and not _linked(run) and run.resolve().parent==work and re.fullmatch(r'mod-extraction-[a-z0-9_-]+-\d{8}-[0-9a-f]{8}',run.name):
        try:
            history_path=run/'cleanup-history.json'
            history=read_json(history_path) if history_path.exists() else []
            history.append(report);write_json(history_path,history)
            write_json(run/'cleanup-result.json',report)
        except OSError as error:report['warnings'].append(str(error))
    return report
