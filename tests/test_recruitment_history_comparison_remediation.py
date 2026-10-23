from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from bonus_platform.engine import recruitment_reconcile as reconcile
from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine import recruitment_special as special
from bonus_platform.engine.recruitment_awards import calculate_draft
from test_recruitment_august_settlement import history_fixture, history_payload, recovery, save
from test_recruitment_review_center import fixture as comparison_fixture


def test_original_notes_and_source_digest_reopen_history_without_payment_claim(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    path=store._folder(state['month'])/'parsed'/(state['sources'][0]['id']+'.json')
    parsed=json.loads(path.read_text());record=parsed['records'][0]
    record.update(role='ledger',historyCells=[{'column':72,'label':'人工备注','value':'3月扣回35.75美元'}])
    record['values']['人工备注']='3月扣回35.75美元';record['ref']['row']=829
    store._write(path,parsed)
    state=store._save(store._folder(state['month']),store._rebuild(store._folder(state['month']),state))
    r=recovery(state)
    assert r['originalNotes'][0]['sourceRef']['row']==829
    assert r['originalNotes'][0]['text']=='3月扣回35.75美元'
    saved=save(store,state,history_payload(state))
    assert not saved['rows'][0]['calculation']['recruitment']['recoveries']
    assert all(n.get('paymentStatus')=='未核实' for n in saved['rows'][0]['calculation']['recruitment']['nodes'])
    changed=deepcopy(saved);changed['rows'][0]['history'][0]['cells'][0]['value']='三月扣款仍待核实'
    calculate_draft(changed)
    assert recovery(changed)['fingerprint']!=r['fingerprint']
    assert any('重新核对' in i['reason'] for i in changed['rows'][0]['calculation']['recruitment']['accountingIssues'])
    changed=deepcopy(saved);changed['sources'][0]['contentDigest']='changed-content'
    calculate_draft(changed)
    assert recovery(changed)['fingerprint']!=r['fingerprint']


def test_existing_partial_full_revoked_and_stale_corrections_remain_visible(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    payload={'revision':state['revision'],'type':'adjustment','basisType':'manual','rowId':state['rows'][0]['id'],
             'kind':'recruitment','role':r['role'],'currency':r['currency'],'recipientId':r['recipientId'],
             'recipientName':r['recipientName'],'amount':-20,'month':202608,'recoveryKey':r['key']}
    partial=save(store,state,payload)
    context=special.context(partial)
    assert context['recoveries'][0]['signedAmount']==-30
    assert context['historyRecoveries'][0]['relatedRecords'][0]['amount']==-20
    assert context['historyRecoveries'][0]['amountEntry']=='blank'
    full=save(store,partial,{**payload,'revision':partial['revision'],'amount':-30})
    assert not special.context(full)['recoveries']
    complete=special.context(full)['historyRecoveries'][0]
    assert complete['resolution']=='adjusted' and len(complete['relatedRecords'])==2
    assert complete['paymentStatus']=='未核实'
    record=complete['relatedRecords'][0]
    revoked=save(store,full,{'revision':full['revision'],'type':'revoke','recordId':record['id']})
    assert any(not x['active'] for x in special.context(revoked)['historyRecoveries'][0]['relatedRecords'])
    changed=deepcopy(revoked);changed['rows'][0]['values']['人工备注']='原备注发生变更'
    calculate_draft(changed)
    assert any(x['issues'] for x in special.context(changed)['historyRecoveries'][0]['relatedRecords'] if x['active'])


def test_missing_historical_payee_stays_missing(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    state['confirmedInstallments'][0].update(recipientId='',recipientName='')
    state['rows'][0]['values']['人工备注']='取消协助'
    calculate_draft(state)
    r=special.context(state)['historyRecoveries'][0]
    assert r['recipientId']==r['recipientName']==''
    assert r['paymentStatus']=='未核实'


def roster_fixture(tmp_path):
    store,state=comparison_fixture(tmp_path)
    path=store._folder(state['month'])/'parsed'/'ledger.json'
    parsed=json.loads(path.read_text());parsed['records'].pop()
    new=deepcopy(parsed['records'][0]);new['values'].update(姓名='线下新增任职',工号='offline-new')
    new['ref']['row']=100;new['historyCells']=[];parsed['records'].append(new)
    store._write(path,parsed)
    return store,store.read(state['month'])


def review_payload(state,d,outcome='pending'):
    return {'revision':state['revision'],'token':uuid4().hex,'sourceId':'ledger','differenceId':d['id'],
            'fingerprint':d['fingerprint'],'outcome':outcome,'basisType':'manual','confirmed':True}


def test_roster_subject_without_platform_id_save_retry_undo_and_cross_month(tmp_path):
    store,state=roster_fixture(tmp_path)
    data=center.project(store,state,'ledger')
    roster=[d for d in data['differences'] if d.get('subject')]
    assert sorted(d['matchStatus'] for d in roster)==['draft_only','unmatched']
    d=next(d for d in roster if d['side']=='reference')
    assert not d['rowId'] and d['subject']['sourceRef']['row']==100
    before=deepcopy([r['calculation'] for r in state['rows']]);payload=review_payload(state,d)
    saved=center.save_review(store,state['month'],payload)
    assert center.save_review(store,state['month'],payload)==saved
    assert [r['calculation'] for r in saved['rows']]==before
    current=next(x for x in center.project(store,saved,'ledger')['differences'] if x['id']==d['id'])
    assert current['status']=='待继续核对' and current['reviewValid']
    undone=store.history_action(state['month'],saved['revision'],'undo')
    assert next(x for x in center.project(store,undone,'ledger')['differences'] if x['id']==d['id'])['status']=='待核对'
    redone=store.history_action(state['month'],undone['revision'],'redo')
    carried=store.carry_forward(202608,202607,0)
    carried_data=center.project(store,carried)
    follow=next(x for x in carried_data['differences'] if x.get('subject'))
    assert carried_data['comparisonReady'] is False
    assert follow['status']=='需重新核对' and not follow['reviewValid'] and follow['originMonth']==202607
    follow_payload=review_payload(carried,follow,'retain');follow_payload['sourceId']=''
    resaved=center.save_review(store,202608,follow_payload)
    reread=next(x for x in center.project(store,resaved)['differences'] if x.get('subject'))
    assert reread['status']=='已确认保留差异' and reread['reviewValid']
    assert reread['fingerprint']==follow['fingerprint']
    assert redone['differenceReviews']


def test_roster_ambiguous_is_neither_unique_omission_nor_platform_only(tmp_path):
    store,state=comparison_fixture(tmp_path)
    path=store._folder(state['month'])/'parsed'/'ledger.json';parsed=json.loads(path.read_text())
    duplicate=deepcopy(parsed['records'][0]);duplicate['ref']['row']=99;parsed['records'].append(duplicate)
    result=reconcile.monthly_comparison(state,parsed['records'],state['sources'][-1])
    assert result['summary']['ambiguousPeople']==2
    assert result['summary']['unmatchedPeople']==0 and result['summary']['draftOnlyPeople']==0
    assert all(d['matchStatus']=='ambiguous' for d in result['rosterDifferences'])


def test_explicit_refusal_blank_month_and_absent_node_are_distinct(tmp_path):
    store,state=comparison_fixture(tmp_path)
    parsed=json.loads((store._folder(state['month'])/'parsed'/'ledger.json').read_text())
    rec=parsed['records'][0]
    rec['historyCells'][0]['value']=30;rec['historyCells'][1]['value']='负责人离职不发'
    refused=reconcile.monthly_comparison(state,parsed['records'],state['sources'][-1])
    d=next(d for d in refused['differences'] if d['rowId']==state['rows'][0]['id'])
    assert d['referenceStatus']=='refused' and d['dimensions']['eligibility']['status']=='blocked'
    rec['historyCells'][1]['value']=''
    blank=reconcile.monthly_comparison(state,parsed['records'],state['sources'][-1])
    d=next(d for d in blank['differences'] if d['rowId']==state['rows'][0]['id'])
    assert d['referenceStatus']=='blank_period'
    rec['historyCells']=[]
    absent=reconcile.monthly_comparison(state,parsed['records'],state['sources'][-1])
    d=next(d for d in absent['differences'] if d['rowId']==state['rows'][0]['id'])
    assert d['referenceStatus']=='absent_node'


def test_frozen_august_four_dimension_denominator_roles_and_complete_roster():
    base=Path(__file__).resolve().parents[1]/'outputs/recruitment-review/august-offline-result-20261019'
    if not all((base/name).is_file() for name in ('draft.json','workbook-parsed.json')):
        pytest.skip('Private frozen August audit evidence is not part of the source distribution')
    state=json.loads((base/'draft.json').read_text());parsed=json.loads((base/'workbook-parsed.json').read_text())
    refs=[r for r in parsed['records'] if r['role']=='ledger'];source={'id':refs[0]['ref']['sourceId'],'name':'202608核对表'}
    before=deepcopy(state['rows']);result=reconcile.monthly_comparison(state,refs,source)
    assert result['summary']['referenceNodes']==438 and result['summary']['equalNodes']==422
    assert result['summary']['additionalQualificationNodes']==3
    assert {t['currency']:(t['reference'],t['calculated']) for t in result['totalsByCurrency']}=={'人民币':(41427,40737),'欧元':(6724.54,6447.78),'美元':(2101.17,2044.87)}
    assert len([d for d in result['differences'] if not d.get('fourDimensionsEqual')])==19
    for row_id,source_row,recipient_id,history_rows in (
        ('95036833d29116c290742265',2088,'zt29046',{4563,4658}),
        ('42cdb383f5d5906f5feae77a',2216,'zt29249',{5295})):
        row=next(r for r in state['rows'] if r['id']==row_id)
        timeline=row['employmentTimelines']['推荐人']
        assert row['values']['推荐人工号']==recipient_id and not row['values']['推荐人转正日期']
        assert {h['source']['row'] for h in timeline}==history_rows
        assert all(h['regularizationDate'] is None and h['approvalStatus']==4 and h['serviceType']==0 for h in timeline)
        previous=next(n for n in row['calculation']['referral']['nodes'] if n['label']=='入职满一个月')
        assert previous['scheduledMonth'] is None and previous['eligibilityReasons']==['推荐人：适用日期尚未转正']
        assert not any(d['rowId']==row_id and d['item']=='推荐人 · 入职满一个月' for d in result['differences'])
    assert result['summary']['unmatchedPeople']==11 and result['summary']['draftOnlyPeople']==3
    assert {d['name'] for d in result['rosterDifferences'] if d['matchStatus']=='unmatched'}=={'Cheng Wang','Steven/Jian Hao Chen','Qimeng Zhang','Qu Lina','杨雪','蒋仁政','刘娜','汪飞','余靖发','梁华生','卢淑敏'}
    assert {d['name'] for d in result['rosterDifferences'] if d['matchStatus']=='draft_only'}=={'干杰','罗之龙','Antonio Gutierrez'}
    will=[d for d in result['differences'] if d['name'].startswith('Will Wang')]
    assert len(will)==2 and all(d['dimensions']['role']['status']=='different' for d in will)
    feng=[d for d in result['differences'] if d['name']=='FENG WEIZE']
    assert len(feng)==1 and all(sum(v['status'] in {'different','blocked'} for v in d['dimensions'].values())>=2 for d in feng)
    daniel=next(d for d in result['differences'] if d['name'].startswith('Daniel Li'))
    assert daniel['referenceStatus']=='refused'
    assert state['rows']==before


def test_approval_person_row_id_links_existing_task_even_when_task_rows_are_empty(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_approval_intake as intake
    store,state=comparison_fixture(tmp_path);rid=state['rows'][0]['id']
    monkeypatch.setattr(intake,'project',lambda store,state:(state,{'items':[{'id':'approval-item','sourceId':'approval-source','person':{'rowId':rid}}]}))
    monkeypatch.setattr(center,'work_items',lambda state,attention:[{'id':'original-task','title':'核对原审批','rowIds':[],'currentRowIds':[],'sourceIds':['approval-source'],'current':True}])
    data=center.project(store,state,'ledger')
    d=next(d for d in data['differences'] if d['rowId']==rid)
    assert d['taskIds']==['original-task'] and d['itemIds']==['approval-item']
    assert len(data['workItems'])==1


def test_roster_saved_conclusion_rechecks_on_reference_change(tmp_path):
    store,state=roster_fixture(tmp_path)
    d=next(d for d in center.project(store,state,'ledger')['differences'] if d.get('matchStatus')=='unmatched')
    saved=center.save_review(store,state['month'],review_payload(state,d,'retain'))
    path=store._folder(state['month'])/'parsed'/'ledger.json';parsed=json.loads(path.read_text())
    parsed['records'][-1]['values']['人工备注']='身份仍需重新核对'
    store._write(path,parsed)
    current=next(d for d in center.project(store,saved,'ledger')['differences'] if d.get('matchStatus')=='unmatched')
    assert current['status']=='需重新核对' and not current['reviewValid']
    with pytest.raises(ValueError,match='差异已变化'):
        center.save_review(store,state['month'],{**review_payload(saved,d),'fingerprint':d['fingerprint']})


def test_new_month_roster_rechecks_once_and_unique_match_resolves_old_followup(tmp_path):
    store,state=roster_fixture(tmp_path)
    d=next(d for d in center.project(store,state,'ledger')['differences'] if d.get('matchStatus')=='unmatched')
    center.save_review(store,state['month'],review_payload(state,d,'retain'))
    carried=store.carry_forward(202608,202607,0)
    old=json.loads((store._folder(202607)/'parsed'/'ledger.json').read_text())
    current_source={**carried['sources'][-1],'id':'new-ledger','storedName':'new.xlsx','name':'202608核对表.xlsx'}
    carried['sources'].append(current_source)
    for rec in old['records']:rec['ref']['sourceId']='new-ledger'
    store._write(store._folder(202608)/'parsed'/'new-ledger.json',old)
    current=center.project(store,carried)
    unmatched=[x for x in current['differences'] if x.get('matchStatus')=='unmatched']
    assert len(unmatched)==1 and unmatched[0]['sourceId']=='new-ledger'
    assert unmatched[0]['status']=='需重新核对' and not unmatched[0]['reviewValid']
    newrow=deepcopy(carried['rows'][0]);newrow['id']='new-platform-row';newrow['values'].update(d['identity'])
    carried['rows'].append(newrow);calculate_draft(carried)
    matched=center.project(store,carried)
    assert not any(x.get('subject') and x.get('name')=='线下新增任职' for x in matched['differences'])
