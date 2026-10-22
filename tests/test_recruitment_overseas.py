from copy import deepcopy
import json

import pytest

from bonus_platform.engine import recruitment_overseas as overseas
from bonus_platform.engine.recruitment_drafts import DraftConflict, DraftStore
from test_recruitment_drafts import book


def snapshot(month=202608):
    period=f'{month//100}-{month%100:02d}'
    return {'version':1,'month':month,'queriedAt':'2026-10-22T18:00:00+08:00',
            'requestedJobNumbers':[],'requestedOfferCodes':[], 'missingOfferCodes':[],
            'roster':[{'scope':'month','data':{'姓名':'候选人','工号':'zt1','证件号码':'TEST-ID',
                'offer流程编号':'OF1','入职日期':period+'-01','人员状态':'试用','离职日期':'',
                '办公地址':'德国','职级':'P1-3','二级部门':'FBU仓储事业部','三级部门':'欧洲区',
                '四级部门':'德国区','五级部门':'测试仓','职位':'专员','直接上级':'经理',
                '直接上级工号':'zt2','人员来源':'OEHR入职','是否虚拟员工':'否'}}],
            'offers':[{'姓名':'候选人','offer编码':'OF1','状态':'已入职','编制ABC分类':'C',
                '招聘负责人':'招聘人','招聘负责人工号':'zt2','协助招聘负责人姓名':'',
                '协助招聘负责人工号':'','招聘渠道':'其他','其他渠道':'中介工转正',
                '招聘启动日期':period+'-01','招聘需求编码':'REQ1','内推人姓名':'','内推人工号':''}]}


def test_first_month_snapshot_builds_new_hires_with_original_source_locations(tmp_path):
    store=DraftStore(tmp_path)
    state=store.save_overseas_snapshot(202608,0,snapshot())
    assert len(state['rows'])==1
    row=state['rows'][0]
    assert row['values']['标签分类']=='海外'
    assert row['values']['海外offer流程编号']=='OF1'
    assert row['values']['招聘渠道']=='外包转正式'
    assert row['offerMatched'] is True
    source=state['sources'][0]
    assert source['forMonth']==202608 and source['kind']=='overseas_api'
    assert not source['snapshotOnly'] and not source['comparisonOnly']
    assert {r['sheet'] for r in row['sources']}=={'OEHR花名册','海外Offer'}


def test_existing_people_edits_operations_and_todos_are_not_applied_over(tmp_path):
    store=DraftStore(tmp_path)
    before=store.ingest(202608,[('roster.xlsx',book(
        ['姓名','工号','offer流程编号','入职日期','人员状态','人员来源','二级部门'],
        [['原姓名','zt1','OF1','2026-08-01','试用','OEHR入职','德国区']]))],0)
    row=before['rows'][0]
    before=store.change(202608,before['revision'],{'edits':[{'rowId':row['id'],
        'field':'招聘负责人姓名','value':'已核对负责人','reason':'原有更正'}]})
    protected={k:deepcopy(before.get(k)) for k in ('rows','todos','edits','operations','awardDecisions','installmentPlans')}
    after=store.save_overseas_snapshot(202608,before['revision'],snapshot())
    assert {k:after.get(k) for k in protected}==protected
    assert after['sources'][-1]['snapshotOnly'] is True
    assert after['sources'][-1]['comparisonOnly'] is True
    assert store.refresh(202608,after['revision'])['rows']==protected['rows']
    assert DraftStore(tmp_path).read(202608)['todos']==protected['todos']


def test_repeated_identical_data_deduplicates_even_with_a_new_query_time(tmp_path):
    store=DraftStore(tmp_path);first=store.save_overseas_snapshot(202608,0,snapshot())
    payload=snapshot();payload['queriedAt']='2026-10-22T18:30:00+08:00'
    payload['requestedJobNumbers']=['zt1'];payload['requestedOfferCodes']=['OF1']
    again=store.save_overseas_snapshot(202608,first['revision'],payload)
    assert again['revision']==first['revision']
    assert len(again['sources'])==1


def test_changed_snapshot_preserves_previous_bytes_and_current_results(tmp_path):
    store=DraftStore(tmp_path);first=store.save_overseas_snapshot(202608,0,snapshot())
    original=store._folder(202608)/'sources'/first['sources'][0]['storedName']
    raw=original.read_bytes();before=deepcopy(first['rows']);todos=deepcopy(first['todos'])
    changed=snapshot();changed['roster'][0]['data']['人员状态']='已离职'
    changed['roster'][0]['data']['离职日期']='2026-10-01'
    second=store.save_overseas_snapshot(202608,first['revision'],changed)
    assert len(second['sources'])==2 and original.read_bytes()==raw
    assert second['rows']==before and second['todos']==todos
    assert second['sources'][-1]['snapshotOnly'] is True


def test_saving_only_a_snapshot_never_recalculates_or_reorders_existing_todos(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_awards as awards
    store=DraftStore(tmp_path);before=store.save_overseas_snapshot(202608,0,snapshot())
    def forbidden(*args):pytest.fail('Saving a comparison snapshot must not recalculate existing payroll')
    monkeypatch.setattr(awards,'calculate_draft',forbidden)
    changed=snapshot();changed['offers'][0]['编制ABC分类']='B'
    after=store.save_overseas_snapshot(202608,before['revision'],changed)
    assert after['todos']==before['todos'] and after['rows']==before['rows']
    assert awards.ensure_calculated(after) is after


def test_months_have_independent_files_and_previous_month_is_unchanged(tmp_path):
    store=DraftStore(tmp_path);aug=store.save_overseas_snapshot(202608,0,snapshot())
    before=(store._folder(202608)/'draft.json').read_bytes()
    sept=store.save_overseas_snapshot(202609,0,snapshot(202609))
    assert sept['rows'][0]['values']['入职日期']=='2026-09-01'
    assert sept['sources'][0]['forMonth']==202609
    assert (store._folder(202608)/'draft.json').read_bytes()==before
    assert aug['sources'][0]['id']!=sept['sources'][0]['id']


def test_wrong_month_and_stale_revision_do_not_write_snapshot_files(tmp_path):
    store=DraftStore(tmp_path)
    with pytest.raises(ValueError,match='月份'):store.save_overseas_snapshot(202608,0,snapshot(202609))
    assert not list(tmp_path.rglob('sources/*.json'))
    state=store.save_overseas_snapshot(202608,0,snapshot())
    old=list((store._folder(202608)/'sources').iterdir())
    with pytest.raises(DraftConflict):store.save_overseas_snapshot(202608,0,snapshot())
    assert list((store._folder(202608)/'sources').iterdir())==old
    assert store.read(202608)['revision']==state['revision']


def test_missing_offer_is_a_real_gap_but_missing_flow_number_does_not_add_people(tmp_path):
    store=DraftStore(tmp_path);payload=snapshot();payload['offers']=[];payload['missingOfferCodes']=['OF1']
    second=deepcopy(payload['roster'][0]);second['data'].update(工号='zt3',姓名='无编号',**{'offer流程编号':''})
    payload['roster'].append(second)
    state=store.save_overseas_snapshot(202608,0,payload)
    assert [r['values']['工号'] for r in state['rows']]==['zt1']
    assert any(t['kind']=='missing_offer' for t in state['todos'])
    assert state['intakeSummary']['excludedByReason']['oehrMissingOffer']==1


def test_recipient_lookup_is_employment_evidence_and_not_an_extra_new_candidate(tmp_path):
    payload=snapshot();actor=deepcopy(payload['roster'][0]);actor['scope']='lookup'
    actor['data'].update(姓名='招聘人',工号='zt2',人员来源='EHR入职',**{'offer流程编号':'','入职日期':'2026-08-02'})
    payload['roster'].append(actor)
    state=DraftStore(tmp_path).save_overseas_snapshot(202608,0,payload)
    assert [r['values']['工号'] for r in state['rows']]==['zt1']


def test_snapshot_scope_does_not_rescan_unmatched_historical_offers():
    rows=[{'values':{'标签分类':'海外','工号':'zt1','入职日期':'2026-06-01','海外offer流程编号':'OLD'},'offerMatched':False},
          {'values':{'标签分类':'海外','工号':'zt2','入职日期':'2026-08-01','海外offer流程编号':'CURRENT'},'offerMatched':False}]
    result=overseas.scope({'month':202608,'rows':rows})
    assert result['offer_codes']==['current']
    assert result['job_numbers']==['zt1','zt2']


def test_browser_result_file_is_accepted_when_cli_logs_go_to_stderr(tmp_path,monkeypatch):
    class Process:
        returncode=0
        def communicate(self,input=None,timeout=None):
            options=json.loads(input.split('await run(',1)[1].rsplit(');',1)[0])
            from pathlib import Path
            Path(options['resultFile']).write_text(json.dumps(snapshot()))
            return '', 'OVERSEAS_SNAPSHOT:ok\n'
    monkeypatch.setattr(overseas.shutil,'which',lambda _: '/fake/ego-browser')
    monkeypatch.setattr(overseas.subprocess,'Popen',lambda *a,**k:Process())
    assert overseas.BrowserClient().fetch(202608)['roster'][0]['data']['工号']=='zt1'


def test_browser_login_error_in_stderr_is_reported_without_saving_snapshot(monkeypatch):
    class Process:
        returncode=0
        def communicate(self,input=None,timeout=None):return '', 'OVERSEAS_ERROR:LOGIN_REQUIRED\n'
    monkeypatch.setattr(overseas.shutil,'which',lambda _: '/fake/ego-browser')
    monkeypatch.setattr(overseas.subprocess,'Popen',lambda *a,**k:Process())
    with pytest.raises(ValueError,match='登录'):overseas.BrowserClient().fetch(202608)


@pytest.mark.parametrize('change',[
    lambda p:p['roster'][0]['data'].update(入职日期='2026-09-01'),
    lambda p:p['offers'].append(deepcopy(p['offers'][0])),
    lambda p:p['offers'][0].update(**{'offer编码':'unrequested'}),
])
def test_incomplete_or_wrong_scope_responses_are_rejected(change):
    payload=snapshot();change(payload)
    with pytest.raises(ValueError):overseas.validate_snapshot(payload,202608)


def test_snapshot_discards_unneeded_personal_fields_and_authentication_values(tmp_path):
    payload=snapshot();payload['ztToken']='never-save';payload['roster'][0]['data']['bankCardNumber']='never-save'
    payload['offers'][0]['mobile']='never-save'
    state=DraftStore(tmp_path).save_overseas_snapshot(202608,0,payload)
    folder=tmp_path/'202608'
    stored=(folder/'sources'/state['sources'][0]['storedName']).read_text()
    assert 'never-save' not in stored and 'bankCardNumber' not in stored


def test_carry_forward_retains_prior_month_sources_without_upgrading_them_to_current(tmp_path):
    store=DraftStore(tmp_path);first=store.save_overseas_snapshot(202608,0,snapshot())
    next_state=store.carry_forward(202609,202608,0)
    previous=(store._folder(202608)/'draft.json').read_bytes()
    next_state=store.save_overseas_snapshot(202609,next_state['revision'],snapshot(202609))
    assert len(next_state['rows'])==2
    assert next_state['sources'][0]['forMonth']==202608
    assert next_state['sources'][-1]['forMonth']==202609
    assert not next_state['sources'][-1]['snapshotOnly']
    assert (store._folder(202608)/'draft.json').read_bytes()==previous


def wait_job(store):
    from bonus_platform.engine import recruitment_prepare as jobs
    import time
    for _ in range(500):
        result=jobs.read(store,202608)
        if result['status'] not in {'running','cancelling'}:return result
        time.sleep(.01)
    pytest.fail('Overseas sync did not finish')


def test_overseas_job_keeps_existing_todos_and_does_not_query_domestic_or_approvals(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_prepare as jobs,recruitment_beisen as domestic
    from types import SimpleNamespace
    store=DraftStore(tmp_path);before=store.save_overseas_snapshot(202608,0,snapshot())
    changed=snapshot();changed['offers'][0]['编制ABC分类']='B'
    store.overseas_client=SimpleNamespace(fetch=lambda *args:changed)
    monkeypatch.setattr(domestic,'fetch',lambda *a,**k:pytest.fail('Overseas sync must not query domestic HR'))
    jobs.start(store,202608,before['revision'],overseas_only=True)
    assert wait_job(store)['status']=='complete'
    after=store.read(202608)
    assert after['rows']==before['rows'] and after['todos']==before['todos']
    assert len(after['sources'])==2


def test_failed_foreign_query_leaves_the_current_month_bytes_unchanged(tmp_path):
    from bonus_platform.engine import recruitment_prepare as jobs
    from types import SimpleNamespace
    store=DraftStore(tmp_path);before=store.save_overseas_snapshot(202608,0,snapshot())
    raw=(store._folder(202608)/'draft.json').read_bytes()
    def failing(*args):raise ValueError('接口未完整返回')
    store.overseas_client=SimpleNamespace(fetch=failing)
    jobs.start(store,202608,before['revision'],overseas_only=True)
    assert wait_job(store)['status']=='failed'
    assert (store._folder(202608)/'draft.json').read_bytes()==raw


@pytest.mark.parametrize('action',['cancel','edit'])
def test_cancel_or_concurrent_edit_cannot_commit_inflight_snapshot(tmp_path,action):
    from threading import Event
    from types import SimpleNamespace
    from bonus_platform.engine import recruitment_prepare as jobs
    store=DraftStore(tmp_path);before=store.save_overseas_snapshot(202608,0,snapshot())
    entered,release=Event(),Event()
    changed=snapshot();changed['offers'][0]['编制ABC分类']='B'
    def blocked(*args):entered.set();assert release.wait(5);return changed
    store.overseas_client=SimpleNamespace(fetch=blocked)
    job=jobs.start(store,202608,before['revision'],overseas_only=True)
    assert entered.wait(2)
    try:
        if action=='cancel':jobs.cancel(store,202608,job['id'])
        else:store.change(202608,before['revision'],{'edits':[{'rowId':before['rows'][0]['id'],'field':'姓名','value':'新的更正'}]})
        protected=(store._folder(202608)/'draft.json').read_bytes()
    finally:release.set()
    assert wait_job(store)['status']==('cancelled' if action=='cancel' else 'failed')
    assert (store._folder(202608)/'draft.json').read_bytes()==protected
    assert len(list((store._folder(202608)/'sources').iterdir()))==1
