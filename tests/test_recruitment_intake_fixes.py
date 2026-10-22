from datetime import datetime

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_awards import status_at
from bonus_platform.engine import recruitment_beisen as adapter, recruitment_prepare as jobs
from test_recruitment_drafts import book


ROSTER = ['姓名','工号','入职日期','人员状态','人员来源','证件号','职级']
SUPPLEMENT = ['体系外人员编号','姓名','证件号','入职日期','人员状态','标签分类','工作地','职级']
OFFER = ['姓名','证件号','工号','入职日期','编制ABC分类','招聘负责人工号','招聘渠道','招聘启动日期','审批状态','是否作废']
OVERSEAS = ['offer编码','招聘需求编码','编制ABC分类','招聘负责人工号','招聘渠道','其他渠道','招聘启动日期','状态']


def test_identity_alias_keeps_original_row_and_edits(tmp_path):
    store = DraftStore(tmp_path)
    first = store.ingest(202607,[('supplement.xlsx',book(SUPPLEMENT,[['e1','甲','ID1','2026-07-01','正式','国内','中国大陆','P3']]))],0)
    rid = first['rows'][0]['id']
    first = store.change(202607,first['revision'],{'edits':[{'rowId':rid,'field':'人工备注','value':'已核对','reason':'核对资料'}]})
    result = store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']]))],first['revision'])
    assert len(result['rows']) == 1
    assert result['rows'][0]['id'] == rid
    assert result['rows'][0]['values']['工号'] == 'zt1'
    assert result['rows'][0]['values']['人工备注'] == '已核对'
    assert not any(t['kind']=='external_identity' for t in result['todos'])


@pytest.mark.parametrize('reverse',[False,True])
def test_alias_conflict_keeps_distinct_records_and_blocks_duplicate_awards(tmp_path,reverse):
    store = DraftStore(tmp_path)
    files=[('a.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']])),
           ('b.xlsx',book(ROSTER,[['甲','zt2','2026-07-01','正式','EHR入职','ID1','P3']]))]
    result=store.ingest(202607,list(reversed(files)) if reverse else files,0)
    assert len(result['rows'])==2
    assert any(t['kind']=='employment_conflict' and len(t['rowIds'])==2 for t in result['todos'])
    assert all(r['rule']['version']=='unresolved' for r in result['rows'])
    assert all(r['calculation']['recruitment']['total'] is None for r in result['rows'])


def test_missing_identifiers_alone_do_not_create_identity_task(tmp_path):
    result=DraftStore(tmp_path).ingest(202607,[('supplement.xlsx',book(SUPPLEMENT,[['','甲','','2026-07-01','正式','海外','德国','P3']]))],0)
    assert len(result['rows'])==1
    assert not any(t['kind']=='external_identity' for t in result['todos'])


def test_native_oehr_schema_sets_scope_without_filename_guess(tmp_path):
    result=DraftStore(tmp_path).ingest(202607,[('data.xlsx',book(['姓名','工号','offer流程编号','入职日期','人员状态','办公地址','二级部门','职级'],[['海外','ov1','OF1','2026-07-01','正式','德国','德国','P3']]))],0)
    assert len(result['rows'])==1
    assert result['rows'][0]['values']['标签分类']=='海外'
    assert result['intakeSummary']['eligibleNewHires']==1
    assert result['intakeSummary']['excludedByReason']=={}


@pytest.mark.parametrize('status,void',[('已驳回',''),('已通过','是'),('审批未通过','')])
def test_invalid_domestic_offer_never_supplies_facts(tmp_path,status,void):
    result=DraftStore(tmp_path).ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']])),('offer.xlsx',book(OFFER,[['甲','ID1','zt1','2026-07-01','A','zt99','招聘网站','2026-06-01',status,void]]))],0)
    row=result['rows'][0]
    assert not row['offerMatched']
    assert not row['values'].get('ABC类别')
    assert not row['values'].get('招聘负责人工号')
    assert any(t['kind']=='offer_status' for t in result['todos'])


@pytest.mark.parametrize('status,matched',[('已作废',False),('未知新状态',False),('',True),('已入职',True)])
def test_overseas_offer_status_has_explicit_semantics(tmp_path,status,matched):
    result=DraftStore(tmp_path).ingest(202607,[('roster.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源','offer流程编号'],[['甲','ov1','2026-07-01','正式','OEHR入职','OF1']])),('offer.xlsx',book(OVERSEAS,[['OF1','R1','A','ov9','招聘网站','','2026-06-01',status]]))],0)
    row=result['rows'][0]
    assert row['offerMatched'] is matched
    if not matched:
        assert not row['values'].get('ABC类别')
        assert any(t['kind']=='offer_status' for t in result['todos'])


@pytest.mark.parametrize('has_column,manual,expected',[(True,False,''),(False,False,'2026-06-01'),(True,True,'2026-06-10')])
def test_recipient_blank_monthly_exit_preserves_column_semantics_and_override(tmp_path,has_column,manual,expected):
    store=DraftStore(tmp_path)
    ledger=book(['姓名','工号','入职日期','标签分类','ABC类别','职级','招聘渠道','招聘启动日期','招聘负责人工号','招聘负责人人员状态','招聘负责人入职日期','招聘负责人最后工作日'],[['甲','ov1','2026-05-01','海外','A','P3','招聘网站','2026-04-01','ov9','正式','2020-01-01','2026-06-01']],title='附件一-招聘奖金核算明细')
    state=store.ingest(202607,[('ledger.xlsx',ledger)],0)
    if manual:
        state=store.change(202607,state['revision'],{'edits':[{'rowId':state['rows'][0]['id'],'field':'招聘负责人最后工作日','value':'2026-06-10','reason':'人工核对'}]})
    headers=['姓名','工号','offer流程编号','入职日期','人员状态','人员来源','办公地址']
    values=['负责人','ov9','OF9','2020-01-01','正式','OEHR入职','德国']
    if has_column: headers.append('最后工作日');values.append('')
    result=store.ingest(202607,[('roster.xlsx',book(headers,[values]))],state['revision'])
    row=result['rows'][0]
    assert row['values']['招聘负责人最后工作日']==expected
    if has_column:
        assert any(p['value']=='' and p['column']==8 for p in row['provenance']['招聘负责人最后工作日'])
    if not expected: assert status_at(row['values'],'招聘负责人',datetime(2026,7,31))==''


def test_empty_api_response_remains_gap_and_next_prepare_tries_once(tmp_path,monkeypatch):
    class EmptyClient:
        def post(self,path,body): return {'data':[]}
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']]))],0)
    payload=adapter.fetch(['zt1'],client=EmptyClient())
    state=store.save_beisen_snapshot(202607,state['revision'],payload)
    assert state['sources'][-1]['scopeJobNumbers']==[]
    calls=[]
    monkeypatch.setattr(adapter,'fetch',lambda *a,**k: calls.append((a,k)) or payload)
    job={'revision':state['revision'],'status':'running'}
    jobs.run(store,202607,job,False,jobs.key_for(store,202607))
    assert len(calls)==1
    assert job['status']=='complete'
    assert job.get('coverageGaps')


@pytest.mark.parametrize('description,explicit,expected,conflict',[
    ('内部推荐 工号 zt123 推荐人甲','','zt123',False),
    ('内部推荐 zt123 或 zt456','','',True),
    ('内部推荐 工号 zt123 推荐人甲','zt456','zt456',True),
])
def test_embedded_referrer_uses_unique_evidence_and_preserves_conflict(tmp_path,description,explicit,expected,conflict):
    result=DraftStore(tmp_path).ingest(202607,[('roster.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源','offer流程编号'],[['甲','ov1','2026-07-01','正式','OEHR入职','OF1']])),('offer.xlsx',book(OVERSEAS+['推荐人工号'],[['OF1','R1','A','ov9','其他',description,'2026-06-01','已入职',explicit]]))],0)
    row=result['rows'][0]
    assert row['values'].get('推荐人工号','')==expected
    assert ('推荐人工号' in row['unresolvedFields']) is conflict
    if expected=='zt123':
        assert any(p.get('column')==6 and p.get('rawValue')==description for p in row['provenance']['推荐人工号'])


@pytest.mark.parametrize('reverse',[False,True])
def test_alias_resolution_does_not_depend_on_file_order(tmp_path,reverse):
    files=[('supplement.xlsx',book(SUPPLEMENT,[['e1','甲','ID1','2026-07-01','正式','国内','中国大陆','P3']])),
           ('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']]))]
    result=DraftStore(tmp_path).ingest(202607,list(reversed(files)) if reverse else files,0)
    assert len(result['rows'])==1
    assert result['rows'][0]['values']['工号']=='zt1'
    assert result['rows'][0]['values']['体系外人员编号']=='e1'


def test_alias_bridge_preserves_two_existing_row_ids(tmp_path):
    store=DraftStore(tmp_path)
    first=store.ingest(202607,[('supplement.xlsx',book(SUPPLEMENT,[['e1','同名','ID1','2026-07-01','正式','国内','中国大陆','P3']])),
                            ('roster.xlsx',book(ROSTER,[['同名','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    original_ids={r['id'] for r in first['rows']}
    assert len(original_ids)==2
    result=store.ingest(202607,[('bridge.xlsx',book(ROSTER,[['同名','zt1','2026-07-01','正式','EHR入职','ID1','P3']]))],first['revision'])
    assert {r['id'] for r in result['rows']}==original_ids
    assert all(r['rule']['version']=='unresolved' for r in result['rows'])
    assert any(t['kind']=='employment_conflict' and set(t['rowIds'])==original_ids for t in result['todos'])


def test_unknown_roster_scope_remains_visible(tmp_path):
    result=DraftStore(tmp_path).ingest(202607,[('data.xlsx',book(['姓名','工号','入职日期','人员状态','二级部门'],[['甲','ov1','2026-07-01','正式','德国']]))],0)
    assert len(result['rows'])==1
    assert result['intakeSummary']['unknownScope']==1
    assert result['intakeSummary']['excludedByReason']=={}
    assert any(t['kind']=='coverage' and result['rows'][0]['id'] in t['rowIds'] for t in result['todos'])


def _api_payload(number,offer_id,abc='1',queried='2026-10-01T10:00:00'):
    return {'version':1,'queriedAt':queried,'scopeJobNumbers':[number],'scopeRecipientJobNumbers':[],
            'candidateHistories':[{'userID':number,'jobNumber':number,'entryDate':'2026-07-01','startDate':'2026-07-01','stopDate':'9999-12-31','approvalStatus':4,'serviceType':0,'lUOffer':offer_id}],
            'offers':[{'objectId':offer_id,'entryDate':'2026-07-01','approvalStatus':2,'recruitmentRequirement':offer_id,'customProperties':{}}],
            'requirements':[{'requirementId':offer_id,'requirementCode':offer_id,'createDate':'2026-06-01','customProperties':{adapter.ABC:abc}}],
            'recipientHistories':[],'forms':[]}


def test_partial_gap_query_keeps_successful_people_facts_and_coverage(tmp_path,monkeypatch):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    state=store.save_beisen_snapshot(202607,state['revision'],_api_payload('zt1','OF1'))
    rid=state['rows'][0]['id']
    assert state['rows'][0]['values']['ABC类别']=='A'
    state=store.ingest(202607,[('new.xlsx',book(ROSTER,[['乙','zt2','2026-07-01','正式','EHR入职','','P3']]))],state['revision'])
    calls=[]
    monkeypatch.setattr(adapter,'fetch',lambda numbers,**kw:calls.append(numbers) or _api_payload('zt2','OF2','2','2026-10-02T10:00:00'))
    job={'revision':state['revision'],'status':'running'}
    jobs.run(store,202607,job,False,jobs.key_for(store,202607))
    assert calls==[['zt2']]
    result=store.read(202607)
    rows={r['values']['工号']:r for r in result['rows']}
    assert rows['zt1']['id']==rid and rows['zt1']['values']['ABC类别']=='A'
    assert rows['zt2']['values']['ABC类别']=='B'
    assert all(row['offerMatched'] for row in rows.values())
    assert adapter.coverage_sets(result['sources'])['candidateEmployment']=={'zt1','zt2'}
    assert adapter.coverage_sets(result['sources'])['candidateOffer']=={'zt1','zt2'}
    assert job['coverageGaps']==[]


def test_refresh_derives_legacy_coverage_from_cached_responses(tmp_path):
    store=DraftStore(tmp_path)
    payload=_api_payload('zt1','OF1');payload['scopeJobNumbers']=['zt1','zt2']
    state=store.save_beisen_snapshot(202607,0,payload)
    source=state['sources'][0]
    original=(store._folder(202607)/'sources'/source['storedName']).read_bytes()
    source['parserVersion']=13;source.pop('syncCoverage');source['scopeJobNumbers']=['zt1','zt2']
    store._write(store._folder(202607)/'draft.json',state)
    refreshed=store.refresh(202607,state['revision'])
    source=refreshed['sources'][0]
    assert source['scopeJobNumbers']==['zt1']
    assert source['syncCoverage']['candidates']['zt2']['employment'] is False
    assert source['requestedJobNumbers']==['zt1','zt2']
    assert (store._folder(202607)/'sources'/source['storedName']).read_bytes()==original


def test_offer_gap_retry_reuses_proven_employment_and_keeps_query_date(tmp_path,monkeypatch):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    missing=_api_payload('zt1','OF1');missing['offers']=[]
    state=store.save_beisen_snapshot(202607,state['revision'],missing)
    calls=[]
    def fetch(numbers,**options):
        calls.append((numbers,options))
        return _api_payload('zt1','OF1',queried='2026-10-02T10:00:00')
    monkeypatch.setattr(adapter,'fetch',fetch)
    job={'revision':state['revision'],'status':'running'}
    jobs.run(store,202607,job,False,jobs.key_for(store,202607))
    assert len(calls)==1 and calls[0][0]==['zt1']
    assert calls[0][1]['candidate_histories'][0]['_queriedAt']=='2026-10-01T10:00:00'
    assert store.read(202607)['rows'][0]['offerMatched']
    assert job['coverageGaps']==[]


def test_invalid_new_api_offer_does_not_resurrect_old_partial_source(tmp_path):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    old=_api_payload('zt1','OF1')
    old['recipientHistories']=[{'jobNumber':'zt9','userID':9,'approvalStatus':4}]
    state=store.save_beisen_snapshot(202607,state['revision'],old)
    new=_api_payload('zt1','OF1',queried='2026-10-02T10:00:00')
    new['offers'][0]['stdIsDeleted']=True
    result=store.save_beisen_snapshot(202607,state['revision'],new)
    assert not result['rows'][0]['offerMatched']
    assert not result['rows'][0]['values'].get('ABC类别')
    assert adapter.coverage_sets(result['sources'])['candidateOffer']==set()
    assert any(t['kind']=='offer_status' for t in result['todos'])


def test_empty_later_lookup_keeps_previous_positive_evidence(tmp_path):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    state=store.save_beisen_snapshot(202607,state['revision'],_api_payload('zt1','OF1'))
    empty=_api_payload('zt1','OF1',queried='2026-10-02T10:00:00')
    empty['candidateHistories']=[];empty['offers']=[]
    result=store.save_beisen_snapshot(202607,state['revision'],empty)
    assert result['rows'][0]['offerMatched']
    assert result['rows'][0]['values']['ABC类别']=='A'
    assert adapter.coverage_sets(result['sources'])['candidateOffer']=={'zt1'}


def test_rejected_lifecycle_state_overrides_approved_status(tmp_path):
    result=DraftStore(tmp_path).ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','ID1','P3']])),
        ('offer.xlsx',book(OFFER+['状态'],[['甲','ID1','zt1','2026-07-01','A','zt99','招聘网站','2026-06-01','已通过','','已作废']]))],0)
    assert not result['rows'][0]['offerMatched']
    assert not result['rows'][0]['values'].get('ABC类别')


def test_cached_employment_retry_does_not_query_or_refresh_its_proof_date():
    class NeverClient:
        def post(self,path,body):
            pytest.fail('Cached employment must not make an HR request')
    history={'jobNumber':'zt1','userID':1,'approvalStatus':4,'entryDate':'2026-07-01',
             'startDate':'2026-07-01','stopDate':'9999-12-31','_queriedAt':'2026-10-01T10:00:00'}
    result=adapter.fetch(['zt1'],client=NeverClient(),candidate_histories=[history])
    assert result['scopeJobNumbers']==['zt1']
    parsed=adapter.parsed_snapshot(result,'source')
    employment=next(r for r in parsed['records'] if r['role']=='employment_history')
    assert employment['apiEvidence']['queriedAt']=='2026-10-01T10:00:00'


def test_history_only_response_keeps_old_offer_and_remains_retryable(tmp_path,monkeypatch):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    state=store.save_beisen_snapshot(202607,state['revision'],_api_payload('zt1','OF1'))
    newer=_api_payload('zt1','OF1',queried='2026-10-02T10:00:00')
    newer['candidateHistories'][0]['regularizationDate']='2026-07-15'
    newer['offers']=[]
    state=store.save_beisen_snapshot(202607,state['revision'],newer)
    assert state['rows'][0]['offerMatched']
    assert state['rows'][0]['values']['ABC类别']=='A'
    assert adapter.coverage_sets(state['sources'])['candidateOffer']=={'zt1'}
    assert state['rows'][0]['employmentTimelines'][''][0]['regularizationDate']=='2026-07-15'
    calls=[]
    monkeypatch.setattr(adapter,'fetch',lambda numbers,**kw:calls.append((numbers,kw)) or _api_payload('zt1','OF1',queried='2026-10-03T10:00:00'))
    job={'revision':state['revision'],'status':'running'}
    jobs.run(store,202607,job,False,jobs.key_for(store,202607))
    assert len(calls)==1 and calls[0][0]==['zt1']
    assert calls[0][1]['candidate_histories'][0]['_queriedAt']=='2026-10-02T10:00:00'
    assert job['coverageGaps']==[]


@pytest.mark.parametrize('scope,label',[('纳入核算','海外'),('不纳入核算','')])
def test_explicit_scope_correction_closes_unknown_scope_only(tmp_path,scope,label):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('data.xlsx',book(['姓名','工号','入职日期','人员状态','二级部门'],[['甲','ov1','2026-07-01','正式','德国']]))],0)
    rid=state['rows'][0]['id']
    edits=[{'rowId':rid,'field':'核算范围','value':scope,'reason':'已核对范围'}]
    if label:edits.append({'rowId':rid,'field':'标签分类','value':label,'reason':'海外来源'})
    state=store.change(202607,state['revision'],{'edits':edits})
    row=state['rows'][0]
    assert not row.get('intakeScopeUnknown')
    assert state['intakeSummary']['unknownScope']==0
    assert state['intakeSummary']['eligibleNewHires']==(1 if scope=='纳入核算' else 0)
    assert row['rule']['version']=='2026-07'
    assert not any(t['kind'] in {'coverage','hire_date'} and rid in t['rowIds'] for t in state['todos'])
    if scope=='纳入核算':
        assert any(t['kind']=='missing_fields' and rid in t['rowIds'] for t in state['todos'])
        assert row['values']['标签分类']=='海外'


def test_api_offer_without_explicit_status_cannot_replace_proven_offer(tmp_path):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-07-01','正式','EHR入职','','P3']]))],0)
    state=store.save_beisen_snapshot(202607,state['revision'],_api_payload('zt1','OF1'))
    incomplete=_api_payload('zt1','OF1','2',queried='2026-10-02T10:00:00')
    incomplete['offers'][0].pop('approvalStatus')
    result=store.save_beisen_snapshot(202607,state['revision'],incomplete)
    assert result['rows'][0]['offerMatched']
    assert result['rows'][0]['values']['ABC类别']=='A'
    assert adapter.coverage_sets(result['sources'])['candidateOfferGap']=={'zt1'}
