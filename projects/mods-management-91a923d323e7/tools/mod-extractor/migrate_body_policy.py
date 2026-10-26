"""Retire historical candidates; preserve original sources and full models."""
from runner import ROOT,Library,sha256,write_json
from body_policy import evaluate_body
from library_service import archive_rejected_body
lib=Library(ROOT/'model-library');report=[]
for profile,ident in [('iuno','WW-000003'),('denia','WW-000002')]:
    _,before=lib.find(ident);full=sha256(lib.inside(before['files']['full']['path']))
    doc=archive_rejected_body(lib.root,ident,evaluate_body(profile,{}))
    assert 'body' not in doc['files'] and sha256(lib.inside(doc['files']['full']['path']))==full
    report.append({'id':ident,'full_sha256_unchanged':full,'body_status':doc['extraction']['body_status'],
                   'archived_body_sha256':doc['files'].get('rejected_body',{}).get('sha256')})
assert not lib.audit()['errors'];write_json(lib.root/'reports/body-retirement-20261010.json',{'models':report})
print(report)
