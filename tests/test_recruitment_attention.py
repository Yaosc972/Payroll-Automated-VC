from copy import deepcopy
import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine import recruitment_attention as attention
from bonus_platform.engine.recruitment_awards import calculate_draft
from test_recruitment_awards import person
from test_recruitment_drafts import book, ROSTER, OFFER


def state_for(rows, todos, month=202607):
    state={'month':month,'revision':1,'rows':rows,'todos':todos,'sources':[],'edits':[],'summary':{}}
    return calculate_draft(state)


def fact_task(row,kind,title):
    return {'id':kind,'kind':kind,'title':title,'detail':'','rowIds':[row['id']],'sourceIds':[]}


def test_new_hire_future_nodes_do_not_become_current_only_because_hired_this_month():
    row=person(hire='2026-07-15',招聘渠道='其他')
    row['originKinds']=['roster','domestic_offer']
    state=state_for([row],[])
    view=attention.project(state)
    assert not view['current']
    assert view['history']  # Preserved for subsequent preparation, not dismissed.


def test_unknown_award_on_first_of_month_still_blocks_possible_current_node():
    row=person(hire='2026-07-01',招聘渠道='其他')
    view=attention.project(state_for([row],[]))
    assert view['current']


def test_missing_candidate_id_document_or_employee_number_is_not_an_award_task():
    row=person(工号='',证件号='',体系外人员编号='',海外offer流程编号='')
    row['originKinds']=['ledger']
    state=state_for([row],[fact_task(row,'external_identity','补充体系外身份对应')]);before=deepcopy(state)
    assert attention.project(state)['current']==[]
    assert attention.project(state)['history']==[]
    assert state==before and state['rows'][0]['calculation']['recruitment']['total']==55


def test_missing_unused_referrer_does_not_block_recruitment():
    row=person(推荐人工号='zt-unused',推荐人姓名='乙',推荐人职级='P4-1',招聘渠道='招聘网站')
    row['originKinds']=['ledger']
    state=state_for([row],[{**fact_task(row,'missing_recipient','补充领取人 zt-unused 的任职资料'),
                           'recipientId':'zt-unused'}])
    assert row['calculation']['referral']['total']==0
    assert row['calculation']['recruitment']['total']>0
    assert attention.project(state)['current']==[]


def test_missing_used_recruiter_still_requires_review():
    row=person(招聘负责人工号='zt-owner',招聘负责人入职日期='',招聘负责人人员状态='');row['originKinds']=['ledger']
    state=state_for([row],[{**fact_task(row,'missing_recipient','补充领取人 zt-owner 的任职资料'),
                           'recipientId':'zt-owner'}])
    assert any(t['kind']=='recipient' for t in attention.project(state)['current'])


def test_resolved_import_diagnostic_does_not_reopen_employment_task():
    row=person(招聘负责人工号='海外-GL001669',招聘负责人入职日期='',招聘负责人人员状态='')
    row['provenance']={'招聘负责人工号':[{'sourceId':'offline','role':'ledger','value':'海外-GL001669'}]}
    state=state_for([row],[{**fact_task(row,'missing_recipient','补充任职资料'),'recipientId':'海外-gl001669'}])
    assert not attention.project(state)['current']


def test_actual_duplicate_employment_still_requires_resolution_without_id():
    row=person(工号='',证件号='');row['originKinds']=['ledger']
    state=state_for([row],[fact_task(row,'duplicate_source_row','同一台账存在重复任职记录')])
    assert any(t['kind']=='employment' for t in attention.project(state)['current'])


def test_indistinguishable_records_need_duplicate_check_not_an_identity_document():
    one=person(工号='');one['originKinds']=['ledger']
    two=deepcopy(one);two['id']='second-source-record'
    state=state_for([one,two],[])
    todos=attention.project(state)['current']
    assert len(todos)==1 and todos[0]['kind']=='employment'
    assert set(todos[0]['rowIds'])=={one['id'],two['id']}
    assert all(not r['values'].get('工号') and not r['values'].get('证件号') for r in state['rows'])


def test_distinct_identifiers_or_business_facts_do_not_create_a_duplicate_task():
    one=person(工号='zt-one');one['originKinds']=['ledger']
    two=deepcopy(one);two['id']='other';two['values']['工号']='zt-two'
    assert attention.project(state_for([one,two],[]))['current']==[]
    one['values']['工号']='';two['values']['工号']='';two['values']['二级组织']='法国'
    assert attention.project(state_for([one,two],[]))['current']==[]


def test_legacy_rehire_does_not_require_previous_exit_or_block_on_its_conflict():
    row=person(hire='2026-06-01',招聘渠道='二次入职',上次离职日期='2025-01-01',推荐人工号='')
    row['originKinds']=['ledger'];row['unresolvedFields']=['上次离职日期']
    tasks=[fact_task(row,'previous_exit','二次入职：上一段离职日期待核'),fact_task(row,'source_conflict','核对不同来源的上次离职日期')]
    state=state_for([row],tasks)
    assert state['rows'][0]['calculation']['recruitment']['total'] is not None
    assert not any(t['kind']=='rehire' for bucket in attention.project(state).values() if isinstance(bucket,list) for t in bucket)


def test_new_rehire_keeps_previous_exit_as_a_required_fact():
    row=person(招聘渠道='二次入职',上次离职日期='',推荐人工号='');row['originKinds']=['ledger']
    state=state_for([row],[fact_task(row,'previous_exit','二次入职：上一段离职日期待核')])
    assert any(t['kind']=='rehire' for t in attention.project(state)['current'])
    assert row['calculation']['recruitment']['total'] is None


def test_confirmed_non_rehire_channel_does_not_inherit_superseded_exit_requirement():
    row=person(招聘渠道='招聘网站');row['originKinds']=['ledger'];row['unresolvedFields']=['上次离职日期']
    row['conflicts']=[{'field':'招聘渠道','values':['二次入职','招聘网站'],'sourceId':'source'}]
    state=state_for([row],[fact_task(row,'source_conflict','核对不同来源的上次离职日期')])
    assert row['calculation']['recruitment']['total']==55
    assert attention.project(state)['current']==[]


@pytest.mark.parametrize('hire',['2026-06-01','2026-07-01'])
def test_equivalent_grade_variants_do_not_block_or_require_manual_choice(hire):
    row=person(hire=hire);row['originKinds']=['ledger'];row['unresolvedFields']=['职级']
    row['conflicts']=[{'field':'职级','values':['P1-1','P1-3'],'sourceId':'source'}]
    state=state_for([row],[fact_task(row,'source_conflict','核对不同来源的职级')])
    assert row['calculation']['recruitment']['total'] is not None
    assert row['calculation']['referral']['total'] is not None
    assert not any('职级' in t['title'] for t in attention.project(state)['current'])
    assert row['unresolvedFields']==['职级'] and row['values']['职级']=='P1-1'


@pytest.mark.parametrize('alternative',['P3-1','无法辨认'])
def test_material_or_unknown_grade_difference_remains_blocking(alternative):
    row=person();row['originKinds']=['ledger'];row['unresolvedFields']=['职级']
    row['conflicts']=[{'field':'职级','values':['P1-1',alternative],'sourceId':'source'}]
    state=state_for([row],[fact_task(row,'source_conflict','核对不同来源的职级')])
    assert row['calculation']['recruitment']['total'] is None
    assert any('职级' in t['title'] for t in attention.project(state)['current'])


def test_recipient_id_conflict_is_one_fact_and_is_not_hidden_as_display_info():
    row=person();row['originKinds']=['ledger'];row['unresolvedFields']=['招聘负责人工号']
    row['conflicts']=[{'field':'招聘负责人工号','values':['zt-owner','zt-other'],'sourceId':'source'}]
    state=state_for([row],[fact_task(row,'source_conflict','核对不同来源的招聘负责人工号')])
    todos=attention.project(state)['current']
    assert [(t['kind'],t['rowIds']) for t in todos]==[('field:招聘负责人工号',[row['id']])]


def test_candidate_status_wording_that_keeps_same_employment_result_is_not_a_task():
    row=person(hire='2026-06-04',人员状态='离职',最后工作日='2026-07-16',推荐人工号='')
    row['originKinds']=['ledger'];row['unresolvedFields']=['人员状态']
    row['conflicts']=[{'field':'人员状态','values':['离职','试用'],'sourceId':'source'}]
    state=state_for([row],[fact_task(row,'source_conflict','核对不同来源的人员状态')])
    assert not any(t['kind']=='field:人员状态' for t in attention.project(state)['current'])


@pytest.mark.parametrize('description',['招聘会','线下招聘会','本地招聘会','广告','招聘广告'])
def test_direct_recruitment_descriptions_are_consistent_with_website_channel(description):
    from bonus_platform.engine.recruitment_import_validation import _normalize_offer_channel
    from bonus_platform.engine.recruitment_awards import channel
    assert _normalize_offer_channel('其他',description)==('招聘网站',False)
    assert channel(person(招聘渠道='其他',其他渠道=description)['values'],'2026-07')[0]==1


def test_unknown_channel_is_still_unknown():
    from bonus_platform.engine.recruitment_import_validation import _normalize_offer_channel
    assert _normalize_offer_channel('其他','待核实的业务来源')==('其他',True)


def test_projection_keeps_history_and_deduplicates_one_shared_fact():
    current=person(职级='P2-1');current['id']='current';current['unresolvedFields']=['职级'];current['originKinds']=['ledger']
    old=person(hire='2025-01-01',职级='P2-1');old['id']='old';old['unresolvedFields']=['职级'];old['originKinds']=['ledger']
    task={'id':'grade','kind':'source_conflict','title':'核对不同来源的职级','detail':'','rowIds':['current','old'],'sourceIds':['source']}
    state=state_for([current,old],[task]);before=deepcopy(state)
    view=attention.project(state)
    assert len([t for t in view['current'] if '职级' in t['title']])==1
    assert next(t for t in view['current'] if '职级' in t['title'])['rowIds']==['current']
    assert any('old' in t['rowIds'] for t in view['history'])
    assert state==before


def test_due_history_stays_current_even_when_hire_was_earlier():
    row=person(hire='2025-01-01',职级='P2-1');row['id']='old';row['unresolvedFields']=['职级'];row['originKinds']=['ledger']
    row['history']=[{'ref':{'sourceId':'history'},'cells':[{'label':'招聘人转正奖金 / 转正发放周期','value':202607}], 'paymentStatus':'unverified'}]
    state=state_for([row],[])
    assert any('old' in t['rowIds'] for t in attention.project(state)['current'])
    assert state['rows'][0]['history'][0]['paymentStatus']=='unverified'


def test_no_award_does_not_request_irrelevant_recruiter_facts():
    row=person(招聘渠道='内部调动',招聘负责人工号='',推荐人工号='');row['originKinds']=['ledger']
    tasks=[{'id':'missing','kind':'missing_fields','title':'补充核算所需信息：招聘启动日期、招聘负责人工号','detail':'','rowIds':[row['id']],'sourceIds':[]}]
    state=state_for([row],tasks)
    assert attention.project(state)['current']==[]
    assert len(state['rows'])==1


def test_unmatched_roster_preserves_actual_fields_for_one_grouped_work_item():
    row=person();row['originKinds']=['roster'];row['offerMatched']=False;row['values'].update(招聘渠道='',职级='',招聘负责人工号='')
    tasks=[{'id':k,'kind':k,'title':title,'detail':'','rowIds':[row['id']],'sourceIds':[]} for k,title in [('missing_offer','国内人员待补Offer或核对调动范围'),('missing_fields','补充核算所需信息：职级、招聘渠道、招聘负责人工号')]]
    view=attention.project(state_for([row],tasks))
    assert any(t['kind']=='field:招聘渠道' for t in view['current'])
    from bonus_platform.engine.recruitment_work_items import project
    items=project(state_for([row],tasks),view)
    assert len(items)==1 and items[0]['mode']=='intake'


def test_current_roster_manager_is_not_conflicted_by_offer_snapshot(tmp_path):
    store=DraftStore(tmp_path)
    headers=ROSTER+['直接上级','直接上级工号','身份证']
    value=['甲','zt1','','2026-07-01','正式','','','EHR入职','中国','中国','现上级','zt2','ID1']
    source=['姓名','身份证','编制ABC分类','招聘负责人工号','招聘渠道','直接上级','直接上级工号']
    state=store.ingest(202607,[('人员.xlsx',book(headers,[value])),('录用.xlsx',book(source,[['甲','ID1','C','zt-owner','招聘网站','原上级','zt3']]))],0)
    row=state['rows'][0]
    assert row['values']['直线经理工号']=='zt2'
    assert '直线经理工号' not in row['unresolvedFields']
    assert len(row['provenance']['直线经理工号'])==2


def test_period_uses_ledger_month_and_ignores_offer_export_date():
    assert attention.named_month(['国内全部Offer_20260805200011.xlsx','全球招聘奖金核算明细表（非操作类）202607.xlsx'])==202607
    assert attention.named_month(['海外纵腾集团_offer20260804.xlsx']) is None


def test_two_current_roster_values_still_need_resolution(tmp_path):
    store=DraftStore(tmp_path)
    headers=ROSTER+['直接上级工号']
    records=[['甲','zt1','OF1','2026-07-01','正式','','','EHR入职','中国','中国',manager] for manager in ('zt2','zt3')]
    state=store.ingest(202607,[('人员.xlsx',book(headers,records))],0)
    row=state['rows'][0]
    assert '直线经理工号' in row['unresolvedFields']
    changed=store.change(202607,state['revision'],{'edits':[{'rowId':row['id'],'field':'直线经理工号','value':'zt4','reason':'核对本次任职'}]})
    assert changed['rows'][0]['values']['直线经理工号']=='zt4'
    assert '直线经理工号' not in changed['rows'][0]['unresolvedFields']


def test_current_due_installment_and_current_edit_remain_visible():
    row=person(hire='2026-01-31',职级='P2-1');row['unresolvedFields']=['职级'];row['originKinds']=['ledger']
    state=state_for([row],[])
    assert any(row['id'] in t['rowIds'] for t in attention.project(state)['current'])
    row=person(hire='2024-01-01',职级='P2-1');row['unresolvedFields']=['职级'];row['originKinds']=['ledger']
    state=state_for([row],[])
    state.update(operations=[{'id':'edit','active':True,'month':202607}],edits=[{'rowId':row['id'],'operationId':'edit','active':True}])
    assert any(row['id'] in t['rowIds'] for t in attention.project(state)['current'])


def ledger_file():
    return ('全球招聘奖金核算明细202607.xlsx',book(['姓名','工号','入职日期','招聘负责人工号'],[['甲','zt1','2026-07-01','zt-owner']],title='附件一-招聘奖金核算明细'))


@pytest.mark.parametrize('hire,current',[('2024-01-01',False),('2026-01-31',True)])
def test_continuity_note_keeps_actual_installment_scope(hire,current):
    row=person(hire=hire,职级='P2-1');row['unresolvedFields']=['职级'];row['originKinds']=['ledger']
    state=state_for([row],[])
    state.update(operations=[{'id':'continuity','active':True,'month':202607}],
                 edits=[{'rowId':row['id'],'field':'任职说明','operationId':'continuity','active':True}])
    projected=attention.project(state)
    assert any(row['id'] in t['rowIds'] for t in projected['current']) is current
    if not current:
        assert any(row['id'] in t['rowIds'] for t in projected['history'])


def test_period_correction_preserves_original_and_target_edits_is_idempotent(tmp_path):
    store=DraftStore(tmp_path)
    source=ledger_file()
    wrong=store.ingest(202609,[source],0)
    target=store.ingest(202607,[source],0)
    target=store.change(202607,target['revision'],{'edits':[{'rowId':target['rows'][0]['id'],'field':'招聘负责人工号','value':'zt-verified','reason':'原件核对'}]})
    corrected=store.correct_period(202609,wrong['revision'])
    assert corrected==target
    assert store.read(202609)==wrong
    assert store.correct_period(202609,wrong['revision'])==target
    with pytest.raises(ValueError): store.correct_period(202609,0)


def test_period_correction_copies_sources_and_reassembles_missing_month_cohort(tmp_path):
    store=DraftStore(tmp_path)
    roster=book(ROSTER,[['乙','zt2','','2026-07-10','正式','','','EHR入职','中国','中国']])
    wrong=store.ingest(202609,[ledger_file(),('花名册.xlsx',roster)],0)
    assert len(wrong['rows'])==1
    corrected=store.correct_period(202609,wrong['revision'])
    assert corrected['month']==202607 and len(corrected['rows'])==2
    assert corrected['summary']['newHires']==2
    assert store.read(202609)==wrong


def test_explicit_month_baseline_and_carry_are_not_auto_corrected():
    state={'month':202609,'sources':[{'name':ledger_file()[0],'roles':['ledger']}]}
    assert attention.period_info(state)['canAlign']
    for key,value in [('baseline','ledger'),('parentMonth',202608),('periodConfirmed',True)]:
        assert not attention.period_info({**state,key:value})['mismatch']
    assert not attention.period_info({**state,'edits':[{'field':'职级'}]})['canAlign']


def test_upload_month_guard_and_explicit_override(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from bonus_platform.app import app
    from bonus_platform import recruitment_draft_api as api
    store=DraftStore(tmp_path);monkeypatch.setattr(api,'store',store)
    client=TestClient(app)
    response=client.post('/api/recruitment/drafts/202609/sources',data={'revision':0},files=[('files',ledger_file())])
    assert response.status_code==409 and response.json()['detail']['suggestedMonth']==202607
    assert store.read(202609)['revision']==0
    response=client.post('/api/recruitment/drafts/202609/sources',data={'revision':0,'periodConfirmed':'true'},files=[('files',ledger_file())])
    assert response.status_code==200
    assert response.json()['month']==202609 and not response.json()['period']['mismatch']
    assert response.json()['summary']['todoGroups']==len(response.json()['todos'])
    assert store.read(202609)['periodConfirmed']
    from io import BytesIO
    from openpyxl import load_workbook
    data=response.json()
    exported=client.get('/api/recruitment/drafts/202609/export')
    sheet=load_workbook(BytesIO(exported.content),read_only=True)['集中待办']
    rows=list(sheet.values)
    expected=[(scope,t['title']) for key,scope in [('todos','本月待办'),('historyTodos','历史待核')] for t in data[key]]
    assert rows[0][:2]==('范围','事项')
    assert [r[:2] for r in rows[1:]]==expected
