"""Current body policy report; historical two-sample verification is retained."""
from runner import ROOT,Library,inventory,read_json,write_json
lib=Library(ROOT/'model-library');rows=[]
for _,doc in lib.documents()[0]:
    if doc['id'] not in ('WW-000002','WW-000003'):continue
    _,source=lib.find(doc['source_id'],source=True);manifest,digest=inventory(source['original_path'])
    assert digest==source['manifest_sha256'] and manifest==source['manifest']
    rows.append({'id':doc['id'],'source_unchanged':True,'full_preserved':'full' in doc['files'],
        'body_status':doc['extraction'].get('body_status','unverified'),
        'active_body_file':'body' in doc['files'],'reason':doc['extraction'].get('body_reason')})
audit=lib.audit();assert not audit['errors']
write_json(ROOT/'model-library/reports/body-policy-verification-20261010.json',{'models':rows,'audit_errors':audit['errors']})
print(rows)
