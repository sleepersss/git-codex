"""Copy-first, recoverable retirement of partial body candidates."""
from pathlib import Path
import shutil,copy
from runner import Library,locked,read_json,write_json,sha256,now

def commit_metadata(path,doc):write_json(path,doc)

def display_warning(result):
    if result.get('full_status')=='partial':return '仅保存源基础网格，动态形态尚未还原；该结果不能作为完整 Mod 入库。'
    return '部分切换状态无法确定，相关网格暂未显示；请查看任务报告。' if result.get('default_display',{}).get('status')=='unresolved' else ''

def preview_views(job,result):
    if job.get('library_game')=='HSR' and result.get('profile')=='auto':
        return {view:view for view in ('front','back','side','three_quarter')}
    return {'front':'back','back':'front','side':'side','three_quarter':'three_quarter'}

def archive_rejected_body(library_root: Path,asset_id: str,reason: dict) -> dict:
    lib=Library(library_root)
    with locked(lib):
        path,original=lib.find(asset_id)
        if original.get('extraction',{}).get('body_status')=='abandoned' and 'body' not in original['files']:
            return original
        doc=copy.deepcopy(original);folder=path.parent/'rejected';folder.mkdir(exist_ok=True)
        backup=folder/'metadata-before-body-retirement.json'
        if not backup.exists():shutil.copy2(path,backup)
        cleanup=[]
        # Copies are verified before metadata switches references. Originals remain on failure.
        for role,f in list(doc['files'].items()):
            if role!='body' and not role.startswith('preview_'):continue
            source=lib.inside(f['path']);dest=folder/source.name
            if sha256(source)!=f['sha256']:raise ValueError('Retirement input hash changed: '+role)
            if dest.exists():
                if sha256(dest)!=f['sha256']:raise ValueError('Retirement destination differs: '+role)
            else:shutil.copy2(source,dest)
            if sha256(dest)!=f['sha256']:raise ValueError('Retirement copy failed: '+role)
            doc['files']['rejected_'+role]={**f,'path':dest.relative_to(lib.root).as_posix()}
            del doc['files'][role];cleanup.append(source)
        if 'body' in doc.get('technical',{}):
            doc['technical']['rejected_body']=doc['technical'].pop('body')
        doc['extraction'].update(body_status='abandoned',body_completeness='none',
            status='body_abandoned',body_reason=reason)
        doc['variant']='保留 Mod 提取模型；裸模已放弃'
        doc['body']['tags']=[t for t in doc['body'].get('tags',[]) if t not in ('身体候选','待人工分离')]
        doc['body']['tags'].append('裸模已放弃')
        doc['history'].append({'at':now(),'action':'body_candidate_retired','reason':reason,'original_mod_untouched':True})
        commit_metadata(path,doc)
        # After commit, cleanup is limited to copied derived artifacts inside this asset directory.
        for p in cleanup:
            if p.resolve().is_relative_to(path.parent.resolve()) and p.exists():p.unlink()
        lib.rebuild();return doc

def list_assets(library_root: Path,query='',body_status=None):
    lib=Library(library_root);words=query.casefold().split()
    # UI reads authoritative atomic JSON, never rebuilds the shared database while a worker writes.
    import json
    docs=[d for _,d in lib.documents()[0] if all(w in json.dumps(d,ensure_ascii=False).casefold() for w in words)]
    for d in docs:
        d['display_body_status']=d['extraction'].get('body_status','unverified')
    return [d for d in docs if body_status is None or d['display_body_status']==body_status]

def _same_source_configuration(doc,configuration):
    existing=doc.get('extraction',{}).get('configuration')
    if not configuration:return True
    if not existing:
        return doc.get('extraction',{}).get('body_status') in ('abandoned','available')
    return existing==configuration


def import_result(library_root: Path,run: Path) -> dict:
    run=Path(run);result=read_json(run/'pipeline-result.json');job=read_json(run/'job.json')
    if result['status']!='passed' or result.get('full_status')!='verified':raise ValueError('完整模型尚未通过核对，不能入库')
    lib=Library(library_root)
    if Path(job.get('library_root','')).resolve()!=lib.root:
        raise ValueError('任务来自另一素材库，请恢复该任务原来的素材库设置后再入库')
    with locked(lib):
        _,source=lib.find(job['source_id'],source=True)
        if source['manifest_sha256']!=job.get('source_manifest_sha256'):
            raise ValueError('任务来源清单与素材库不匹配')
        configuration=job.get('configuration')
        existing=[d for d in lib.search(game=job['library_game']) if d['source_id']==job['source_id'] and
            _same_source_configuration(d,configuration)]
        file=result['files']['full'];full=Path(file['path'])
        if not full.resolve().is_relative_to(run.resolve()) or sha256(full)!=file['sha256']:raise ValueError('模型路径或哈希改变')
        body=None
        if result['body_status']=='available':
            b=result['files']['body'];body=Path(b['path'])
            if not body.resolve().is_relative_to(run.resolve()) or sha256(body)!=b['sha256']:raise ValueError('身体哈希改变')
        if existing:
            doc=existing[0]
            if doc['extraction'].get('body_status') in ('abandoned','available'):
                if configuration and doc['extraction'].get('configuration') and doc['extraction'].get('model_fingerprints')!=result.get('verification',{}).get('fingerprints'):
                    raise ValueError('该配置已有不同的提取结果，当前模型尚未入库；请先核查已有记录')
                stored=doc['files'].get('full')
                if not stored or sha256(lib.inside(stored['path']))!=stored['sha256']:
                    raise ValueError('已有素材文件哈希改变，请先核查')
                if body is None:return doc
                if 'body' in doc['files']:
                    stored_body=doc['files']['body']
                    if sha256(lib.inside(stored_body['path']))!=stored_body['sha256']:raise ValueError('已有身体文件哈希改变')
                    if stored_body['sha256']==result['files']['body']['sha256'] or (result.get('body_fingerprints') and doc['extraction'].get('body_fingerprints')==result['body_fingerprints']):return doc
                    raise ValueError('已有身体与本次选择不同，未覆盖已有身体；请核查或保留为另一变体')
            elif doc['files'].get('full',{}).get('sha256')!=file['sha256']:
                raise ValueError('已有记录尚未完成且模型不同，需先核查或迁移记录')
        else:
            import re
            character=job.get('character') or {'denia':'Denia','iuno':'Iuno'}[job['name']]
            character=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',character)[:80].rstrip(' .') or '未命名人物'
            doc=lib.register(job['library_game'],character,job['source_id'],full,body,
                             variant=('Mod 提取模型；裸模已放弃' if result['body_status']=='abandoned' else 'Mod 提取模型；身体待核对') if body is None else '已核对身体')
        path,doc=lib.find(doc['id'])
        if body is not None and 'body' not in doc['files']:
            dest=path.parent/'body.blend'
            if dest.exists() and sha256(dest)!=result['files']['body']['sha256']:raise ValueError('目标身体文件与本次结果不同，未覆盖')
            if not dest.exists():shutil.copy2(body,dest)
            if sha256(dest)!=result['files']['body']['sha256']:raise ValueError('身体复制核对失败')
            doc['files']['body']={'path':dest.relative_to(lib.root).as_posix(),'sha256':sha256(dest),'size':dest.stat().st_size}
        if body is not None and sha256(lib.inside(doc['files']['body']['path']))!=result['files']['body']['sha256']:
            raise ValueError('未完成记录的身体与本次结果不同')
        doc['extraction'].update(body_status=result['body_status'],body_reason=result['body_reason'],
            body_completeness=result.get('body_completeness','verified_scope' if body else 'none'),status='body_abandoned' if result['body_status']=='abandoned' else 'body_unverified' if body is None else 'files_received')
        if body:
            doc['extraction']['body_fingerprints']=result.get('body_fingerprints');doc['variant']='源裸模已提取并核对（不含头部）'
            doc['body']['tags']=[t for t in doc['body'].get('tags',[]) if t not in ('裸模已放弃','身体候选','待人工分离')]
            if '裸模可用' not in doc['body']['tags']:doc['body']['tags'].append('裸模可用')
            doc['body']['missing_parts']=['原游戏头部和头发（本次输出范围之外）']
            if result.get('manual_body'):
                doc['variant']='用户手动删减并保存的源身体范围'
                doc['extraction']['manual_body']=copy.deepcopy(result['manual_body'])
                doc['body']['missing_parts']=[]
                doc['body']['scope']=result['manual_body']['scope']
                doc['technical']['body']={**copy.deepcopy(result['manual_body']['measurements']),'scope':result['manual_body']['scope']}
        if configuration:doc['extraction'].update(configuration=configuration,model_fingerprints=result.get('verification',{}).get('fingerprints'))
        if 'default_display' in result:doc['extraction']['default_display']=copy.deepcopy(result['default_display'])
        doc['history'].append({'at':now(),'action':'desktop_result_imported','task':str(run)})
        views=run/('full-previews' if body is None else 'body-previews')
        for view,rendered in preview_views(job,result).items():
            source=views/(rendered+'.png')
            if source.exists():
                dest=path.parent/'previews'/('body_' if body else 'full_')/source.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
                doc['files'][('preview_' if body else 'full_preview_')+view]={'path':dest.relative_to(lib.root).as_posix(),'sha256':sha256(dest),'size':dest.stat().st_size}
        if body:
            for name in ('body-analysis.json','body-selection.json','body-source-verification.json',* (('manual-body.json',) if result.get('manual_body') else ())):
                source=run/name
                if not source.exists():continue
                dest=path.parent/'validation'/('v3-'+name);dest.parent.mkdir(exist_ok=True)
                if dest.exists() and sha256(dest)!=sha256(source):
                    import uuid
                    dest=dest.with_name('v3-'+uuid.uuid4().hex[:8]+'-'+name)
                shutil.copy2(source,dest)
                doc['files']['validation_'+name.removesuffix('.json').replace('-','_')]={'path':dest.relative_to(lib.root).as_posix(),'sha256':sha256(dest),'size':dest.stat().st_size}
        commit_metadata(path,doc);lib.rebuild();return doc
