"""Local verified repair results -> additive upgrades, preserving full files and history."""
from pathlib import Path
import sys,shutil
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runner import Library,read_json,write_json,sha256,now
from library_service import import_result

root=Path(__file__).resolve().parents[2];qa=root/'outputs/mod-extractor-qa';lib=Library(root/'model-library')
before=read_json(qa/'v3-library-before.json');upgrades=[]
for sample in ('denia','augusta','carlotta','yaoguang'):
    report=read_json(qa/('v3-'+sample+'-result.json'));run=Path(report['run'])
    assert report['status']=='passed' and report['body_status']=='available'
    assert read_json(run/'body-source-verification.json')['status']=='passed'
    d=import_result(lib.root,run);upgrades.append({'sample':sample,'asset':d['id'],'full_preserved':d['files']['full']['sha256'],'body':d['files']['body']})
    assert import_result(lib.root,run)['id']==d['id']
for original in before:
    _,current=lib.find(original['id'])
    assert current['files']['full']==original['full'],original['id']+' full metadata changed'
    assert sha256(lib.inside(current['files']['full']['path']))==original['full']['sha256']
    if original['body']:assert current['files']['body']==original['body'],original['id']+' old body changed'
    assert len(current['history'])>=original['history_length']
# Actual old runs reanalyzed during diagnosis: retain their original pipeline reports.
old_runs=('mod-extraction-denia-20261010-f3af91d0','mod-extraction-auto-00c8b82beaf6-20261010-8d9da808',
    'mod-extraction-auto-50f876cab282-20261010-ca1927f1','mod-extraction-auto-e5a4a639fc7f-20261010-be52b133',
    'mod-extraction-auto-2653a2e3a922-20261010-17526eda','mod-extraction-auto-00c8b82beaf6-20261011-0c43d125')
for name in old_runs:
    run=root/'work'/name;path=run/'pipeline-result.json';result=read_json(path)
    if result['status']!='passed' or result.get('full_status')!='verified':continue
    decision=read_json(run/'body-decision.json')
    if decision['status']!='eligible':continue
    assert read_json(run/'body-source-verification.json')['status']=='passed'
    assert sha256(Path(result['files']['full']['path']))==result['files']['full']['sha256']
    backup=run/'pipeline-result-before-v3-body-repair.json'
    if not backup.exists():shutil.copy2(path,backup)
    selection=read_json(run/'body-selection.json');body=run/'models/body.blend'
    result.update(body_status='available',body_reason=decision,body_completeness='verified_scope',
        body_fingerprints=selection['fingerprints'],body_reanalyzed_at=now(),body_analysis_version=3)
    result['files']['body']={'path':str(body),'sha256':sha256(body)};write_json(path,result)
audit=lib.audit();assert not audit['errors'],audit['errors']
write_json(qa/'v3-library-upgrade.json',{'at':now(),'upgrades':upgrades,'old_full_hashes_preserved':True,
    'existing_bodies_preserved':True,'history_preserved':True,'audit':audit})
print('Additive upgrades verified:',[(d['sample'],d['asset']) for d in upgrades])
