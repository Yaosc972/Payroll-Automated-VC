from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_employment import enrich
from bonus_platform.engine.recruitment_awards import award, calculate_draft
from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_actions import task_fields
from bonus_platform.engine.recruitment_work_items import project as work_items, detail
from test_recruitment_awards import person
from test_recruitment_drafts import book, ROSTER, OFFER
from test_recruitment_flow import history
from test_recruitment_intake_fixes import OFFER as DOMESTIC_OFFER, ROSTER as DOMESTIC_ROSTER
from test_recruitment_intake_fixes import _api_payload


def state_for(row, todos=(), month=202607):
    row.setdefault('originKinds',['ledger'])
    row.setdefault('sources',[])
    return calculate_draft({'month':month,'revision':1,'rows':[row],'todos':list(todos),
                            'sources':[],'edits':[],'summary':{}})


@pytest.mark.parametrize('field,key,date',[('转正日期','regularizationDate','2026-07-20'),('最后工作日','lastWorkDate','2026-08-15')])
def test_export_blank_adopts_unique_approved_date_but_manual_clear_survives(field,key,date):
    row=person(工号='zt1',标签分类='国内',**{field:''})
    row.update(edits=[],sources=[],provenance={},conflicts=[],monthlyRosterFields=[field])
    enrich(row,{'zt1':[history(**{key:date})]},[])
    assert row['values'][field]==date
    assert not row['conflicts']
    assert any(f['field']==field and f['after']==date for f in row['automaticFacts'])
    row['values'][field]='';row['edits']=[{'field':field}]
    enrich(row,{'zt1':[history(**{key:date})]},[])
    assert row['values'][field]=='' and not row['conflicts']


def test_two_positive_approved_dates_remain_a_source_conflict():
    row=person(工号='zt1',标签分类='国内',最后工作日='')
    row.update(edits=[],sources=[],provenance={},conflicts=[],monthlyRosterFields=['最后工作日'])
    enrich(row,{'zt1':[history(lastWorkDate='2026-08-15'),history(lastWorkDate='2026-08-16')]},[])
    assert row['values']['最后工作日']==''
    assert {p['value'] for p in row['provenance']['最后工作日']}=={'2026-08-15','2026-08-16'}
    assert row['conflicts']


def test_positive_export_and_different_approved_date_remain_unresolved():
    row=person(工号='zt1',标签分类='国内',最后工作日='2026-08-15')
    row.update(edits=[],sources=[],provenance={},conflicts=[],monthlyRosterFields=['最后工作日'])
    enrich(row,{'zt1':[history(lastWorkDate='2026-08-16')]},[])
    assert row['values']['最后工作日']=='2026-08-15'
    assert any(c['field']=='最后工作日' and set(c['values'])=={'2026-08-15','2026-08-16'} for c in row['conflicts'])


def test_valid_current_offer_supersedes_invalid_branch_without_hiding_real_gap(tmp_path):
    store=DraftStore(tmp_path)
    roster=book(DOMESTIC_ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P1-1'],['乙','zt2','2026-07-01','正式','EHR入职','ID2','P1-1']])
    offers=book(DOMESTIC_OFFER,[['甲','ID1','zt1','2026-07-01','C','zt99','招聘网站','2026-06-01','已通过',''],
                              ['甲','ID1','zt1','2026-07-01','C','zt99','招聘网站','2026-06-01','已作废','是'],
                              ['乙','ID2','zt2','2026-07-01','C','zt99','招聘网站','2026-06-01','已作废','是']])
    state=store.ingest(202607,[('roster.xlsx',roster),('国内Offer.xlsx',offers)],0)
    rows={r['values']['工号']:r for r in state['rows']}
    assert rows['zt1']['offerMatched'] and not rows['zt2']['offerMatched']
    assert not any(t['kind']=='offer_status' and rows['zt1']['id'] in t['rowIds'] for t in state['todos'])
    assert any(t['kind']=='offer_status' and rows['zt2']['id'] in t['rowIds'] for t in state['todos'])


@pytest.mark.parametrize('alternative,blocks',[('M2-2',False),('P4-1',True),('无法识别',True)])
def test_referrer_source_conflicts_follow_actual_qualification(alternative,blocks):
    row=person(推荐人职级='P2-2',推荐人职位='销售经理')
    row['unresolvedFields']=['推荐人职级','推荐人职位']
    row['conflicts']=[{'field':'推荐人职级','values':['P2-2',alternative],'sourceId':'roster'},
                      {'field':'推荐人职位','values':['销售经理','宁波组主管'],'sourceId':'roster'}]
    result=award(row,'referral',202607)
    assert (result['total'] is None)==blocks
    if not blocks:assert not result['issues']
    state=state_for(row,[{'id':'qualification','kind':'recipient_conflict','title':'领取人资料存在不同值',
                         'rowIds':[row['id']],'sourceIds':[],'recipientId':'zt-ref'}])
    tasks=[t for scope in ('current','history') for t in project(state)[scope] if t['kind']=='recipient']
    assert bool(tasks)==blocks
    if blocks:
        assert task_fields(row,tasks[0],202607)==['推荐人职级']


def test_real_cycle_and_known_standard_do_not_become_missing_offer_work():
    row=person(招聘启动日期='2026-07-02');row['offerMatched']=False
    state=state_for(row,[{'id':'cycle','kind':'calculation','title':'招聘奖金：招聘起止日期或标准周期待核','rowIds':[row['id']],'sourceIds':[]}])
    groups=work_items(state,project(state))
    assert any(g['key']=='cycle' for g in groups)
    assert not any(g['mode']=='intake' for g in groups)


@pytest.mark.parametrize('raw,description',[('其他','中介公司'),('中介公司','')])
def test_existing_unknown_channel_is_classification_work_without_raw_reentry(raw,description):
    row=person(招聘渠道=raw,其他渠道=description)
    row['channelResolution']={'original':'其他','resolved':False,'sources':[{'value':'中介公司'}]}
    state=state_for(row,[{'id':'channel','kind':'channel','title':'核对其他招聘渠道','rowIds':[row['id']],'sourceIds':[]}])
    groups=work_items(state,project(state))
    group=next(g for g in groups if g['key']=='channel_policy')
    assert group['ruleMaintenance']
    assert [f['field'] for f in detail(state,group)['fields']]==['招聘渠道']
    assert row['calculation']['recruitment']['total'] is None


def test_current_recipient_requirement_uses_real_overseas_roster_and_excludes_future():
    from bonus_platform.engine.recruitment_attention import recipient_requirements
    row=person();state=state_for(row)
    row['recipientSourceRegions']={'招聘负责人':'海外','推荐人':'海外'}
    row['recipientEmploymentEvidence']={'招聘负责人':{'covered':True},'推荐人':{'covered':True}}
    future=deepcopy(row);future['id']='future';future['values']['招聘负责人工号']='zt-future'
    for a in future['calculation'].values():
        if isinstance(a,dict):
            for n in a.get('nodes',[]):n['dueMonth']=202609
    state['rows'].append(future)
    requirements=recipient_requirements(state,202607)
    assert requirements['currentRecipients']=={'zt-owner','zt-ref'}
    assert requirements['coveredRecipients']=={'zt-owner','zt-ref'}
    assert requirements['domesticFetchIds']==set() and requirements['coverageGaps']==[]
    row['recipientEmploymentEvidence']['招聘负责人']={'covered':False,'virtual':True}
    requirements=recipient_requirements(state,202607)
    assert 'zt-owner' not in requirements['coveredRecipients']
    assert requirements['domesticFetchIds']==set()
    assert requirements['coverageGaps']==[{'role':'领取人','employee':'zt-owner','reason':'未取得任职资料'}]


@pytest.mark.parametrize('ledger',[False,True])
def test_malformed_identity_with_proven_employment_does_not_reask_identical_hire_day(tmp_path,ledger):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('人员.xlsx',book(DOMESTIC_ROSTER+['标签分类'],[['甲','zt1','2026-07-01','正式','EHR入职','44538119990327003X','P1-1','国内']],title='附件一-招聘奖金核算明细' if ledger else 'Sheet1')),
                              ('其他人员.xlsx',book(DOMESTIC_ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','WX845581(1)','P1-1']]))],0)
    state=store.save_beisen_snapshot(202607,state['revision'],_api_payload('zt1','OF1'))
    row=state['rows'][0]
    assert len(state['rows'])==1 and row['rule']['version']=='2026-07'
    tasks=[t for scope in ('current','history') for t in project(state)[scope] if row['id'] in t['rowIds']]
    assert not any(t['kind']=='employment' for t in tasks)
    identity=next(t for t in tasks if t['kind']=='identity')
    assert task_fields(row,identity,202607)==['证件号']
    assert {str(p['value']) for p in row['provenance']['证件号']} >= {'44538119990327003X','WX845581(1)'}


def test_recipient_grade_and_position_source_values_are_retained_and_nonblocking(tmp_path):
    store=DraftStore(tmp_path)
    headers=['体系外人员编号','姓名','入职日期','标签分类','工作地','职级','ABC类别','招聘渠道','招聘启动日期','招聘负责人工号','招聘负责人姓名','招聘负责人入职日期','招聘负责人人员状态','推荐人工号','直线经理工号','人员状态']
    state=store.ingest(202607,[('补充.xlsx',book(headers,[['candidate','甲','2026-07-01','海外','德国','P1-1','C','招聘网站','2026-05-20','zt-owner','负责人','2020-01-01','正式','zt-ref','zt-manager','正式']])),
                              ('名册一.xlsx',book(ROSTER+['职级','职位'],[['乙','zt-ref','','2020-01-01','正式','2020-07-01','','EHR入职','中国','中国','M2-2','宁波组主管']])),
                              ('名册二.xlsx',book(ROSTER+['职级','职位'],[['乙','zt-ref','','2020-01-01','正式','2020-07-01','','EHR入职','中国','中国','P2-2','销售经理']]))],0)
    row=next(r for r in state['rows'] if r['values']['姓名']=='甲')
    assert {'推荐人职级','推荐人职位'} <= set(row['unresolvedFields'])
    assert row['calculation']['referral']['total']==400
    assert not row['calculation']['referral']['issues']
    assert not any(t['kind']=='recipient' and row['id'] in t['rowIds'] for scope in ('current','history') for t in project(state)[scope])


def test_completed_prepare_reprojects_stale_recipient_gaps_without_writing(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_prepare as jobs
    store=DraftStore(tmp_path);row=person();state=state_for(row)
    row['recipientSourceRegions']={'招聘负责人':'海外','推荐人':'海外'}
    row['recipientEmploymentEvidence']={'招聘负责人':{'covered':True},'推荐人':{'covered':True}}
    monkeypatch.setattr(store,'read',lambda month:state)
    old={'id':'saved-job','status':'complete','revision':0,'coverageGaps':[
        {'role':'领取人','employee':'zt-owner','reason':'未取得任职资料'},
        {'role':'领取人','employee':'zt-future','reason':'未取得任职资料'}],'message':'2名领取人未取得任职资料'}
    path=store._folder(202607)/'prepare.json';store._write(path,old);before=path.read_bytes()
    current=jobs.read(store,202607)
    assert current['id']=='saved-job' and current['status']=='complete'
    assert current['coverageGaps']==[] and '未取得' not in current['message']
    assert path.read_bytes()==before


def test_coverage_gaps_are_current_business_needs_and_preserve_true_missing_offer():
    from bonus_platform.engine.recruitment_prepare import coverage_gaps
    row=person(hire='2025-12-08',标签分类='国内',推荐人工号='')
    row['offerMatched']=False
    state=state_for(row,month=202608)
    assert coverage_gaps(state,202608)==[]
    missing=person(hire='2026-08-01',工号='zt-new',标签分类='国内',ABC类别='',招聘渠道='',招聘启动日期='',招聘负责人工号='',招聘负责人姓名='',推荐人工号='')
    missing.update(offerMatched=False,originKinds=['roster'])
    state=state_for(missing,[{'id':'offer','kind':'missing_offer','title':'国内人员待补Offer','rowIds':[missing['id']],'sourceIds':[]}],202608)
    assert {'role':'候选人','employee':'zt-new','reason':'未取得有效录用资料'} in coverage_gaps(state,202608)


def test_stale_special_arrangement_opens_adjustment_records_instead_of_history_recovery():
    row=person()
    state=state_for(row)
    reason='资格例外依据或计算事实已变化，请重新核对'
    row['calculation']['recruitment'].setdefault('accountingIssues',[]).append(
        {'accountingMonth':202607,'reason':reason,'recordId':'old-exception'})
    state['todos'].append({'id':'stale-exception','kind':'calculation','title':reason,
                          'rowIds':[row['id']],'sourceIds':[]})
    item=next(i for i in work_items(state,project(state)) if i['key']=='calculation:'+reason)
    assert item['mode']=='specialRecords'
    assert detail(state,item)['fields']==[]


def test_ready_approval_files_share_one_existing_review_entry():
    state=state_for(person())
    state['sources']=[{'id':sid,'name':sid+'.pdf','active':True,'attachment':True,
                      'approvalSummary':{'readyCount':1,'blockedCount':0}} for sid in ('a','b')]
    attention={'current':[{'id':sid,'kind':'attachment_review','title':'核对审批',
                          'rowIds':[],'sourceIds':[sid]} for sid in ('a','b')],'history':[]}
    items=work_items(state,attention)
    assert len(items)==1 and items[0]['key']=='approval:ready'
    assert items[0]['sourceIds']==['a','b']
