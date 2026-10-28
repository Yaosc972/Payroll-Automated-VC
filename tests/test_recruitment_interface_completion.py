from copy import deepcopy
import time

import pytest

from bonus_platform.engine import recruitment_beisen as beisen, recruitment_overseas as overseas, recruitment_prepare as jobs
from bonus_platform.engine.recruitment_drafts import DraftStore, ROLE_FIELDS
from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_employment import enrich, index_histories
from bonus_platform.engine.recruitment_hierarchy import evidence
from bonus_platform.engine.recruitment_awards import award
from test_recruitment_overseas import snapshot
from test_recruitment_awards import person
from test_recruitment_flow import history


MONTH=202609


def test_targeted_offer_fills_gaps_without_new_hires_or_overwriting_manual_work(tmp_path):
    store=DraftStore(tmp_path);p=snapshot(MONTH);p['offers']=[];p['missingOfferCodes']=['OF1']
    before=store.save_overseas_snapshot(MONTH,0,p);rid=before['rows'][0]['id']
    before=store.change(MONTH,before['revision'],{'edits':[{'rowId':rid,'field':'招聘负责人姓名','value':'人工负责人','reason':'已确认'}]})
    original=(store._folder(MONTH)/'sources'/before['sources'][0]['storedName']).read_bytes()
    target=snapshot(MONTH);target.update(offerOnly=True,roster=[],requestedOfferCodes=['OF1'])
    after=store.save_overseas_snapshot(MONTH,before['revision'],target)
    assert len(after['rows'])==1 and after['rows'][0]['offerMatched']
    assert after['rows'][0]['values']['招聘负责人姓名']=='人工负责人'
    assert after['edits']==before['edits'] and not after['sources'][-1]['comparisonOnly']
    assert (store._folder(MONTH)/'sources'/before['sources'][0]['storedName']).read_bytes()==original
    assert store.save_overseas_snapshot(MONTH,after['revision'],target)['revision']==after['revision']
    target['roster']=snapshot(MONTH)['roster']
    with pytest.raises(ValueError,match='录用补查'):overseas.validate_snapshot(target,MONTH)


def test_prepare_repairs_missing_overseas_offer_without_reloading_roster(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);p=snapshot(MONTH);p['offers']=[];p['missingOfferCodes']=['OF1']
    before=store.save_overseas_snapshot(MONTH,0,p);calls=[]
    def fetch(month,codes,**kwargs):
        calls.append(codes);result=snapshot(month)
        result.update(offerOnly=True,roster=[],requestedOfferCodes=['OF1']);return result
    monkeypatch.setattr(overseas,'fetch_offers',fetch)
    monkeypatch.setattr(overseas,'fetch',lambda *a,**k:pytest.fail('A targeted gap must not reload monthly hires'))
    after=jobs.complete_inputs(store,MONTH,before,lambda **k:None)
    assert calls==[['of1']] and after['rows'][0]['offerMatched']
    assert not [t for t in project(after)['current'] if t['rowIds']]


def proof(number,manager,*,start='2026-09-01',end='9999-12-31',entry='2026-09-01',identity=None):
    return {'provider':'oehr','empNo':number,'employeeInfoId':identity or number,'entryDate':entry,'startDate':start,'endDate':end,
            'employmentType':'0','employmentStatus':'0','employeeStatus':'3','lineManagerNo':manager,'lineManagerProvided':'1',
            'queriedAt':'2026-10-26T12:00:00','source':{'sourceId':'api','sheet':'任职','row':number}}


def referral_row():
    row=person(hire='2026-09-01',标签分类='海外',工号='zt1',推荐人工号='zt4',推荐人职级='P1-3',推荐人职位='专员')
    row.update(edits=[],conflicts=[],sources=[],provenance={});return row


def test_reporting_chain_finds_indirect_referrer_at_hire_and_preserves_row():
    row=referral_row();original=deepcopy(row['values'])
    index={'zt1':[proof('zt1','zt2',end='2026-09-15'),proof('zt1','zt9',start='2026-09-16')],
           'zt2':[proof('zt2','zt4',entry='2020-01-01')], 'zt4':[proof('zt4','',entry='2019-01-01')]}
    row['reportingLine']=evidence(row,index)
    assert row['reportingLine']['chain']==['zt2','zt4'] and row['reportingLine']['related']
    result=award(row,'referral',MONTH)
    assert result['total']==0 and '推荐人与候选人属于上下级汇报关系' in result['reasons']
    assert row['values']==original


def test_missing_or_conflicting_manager_does_not_prove_no_relation():
    row=referral_row();index={'zt1':[proof('zt1','zt2')]}
    result=evidence(row,index)
    assert not result['complete'] and result['pending']=={'provider':'either','number':'zt2'}
    index['zt1'].append(proof('zt1','zt3'))
    assert not evidence(row,index)['complete']
    row['edits']=[{'field':'推荐人与候选人上下级关系','value':'否'}]
    assert evidence(row,index) is None
    row['edits']=[];row['frozenRecruitmentFacts']=True
    assert evidence(row,index) is None


def test_domestic_hierarchy_uses_manager_user_id_and_effective_employee_number():
    row=referral_row();row['values']['标签分类']='国内'
    records=[{**history(),'jobNumber':'zt1','userID':1,'entryDate':'2026-09-01','pOIdEmpAdmin':2},
             {**history(),'jobNumber':'zt2','userID':2,'pOIdEmpAdmin':4},
             {**history(),'jobNumber':'zt4','userID':4,'pOIdEmpAdmin':None}]
    payload={'queriedAt':'2026-10-26T12:00:00','candidateHistories':[], 'recipientHistories':records,
             'offers':[],'requirements':[],'forms':[]}
    index=index_histories(beisen.parsed_snapshot(payload,'api')['records'])
    result=evidence(row,index)
    assert result['complete'] and result['related'] and result['chain']==['zt2','zt4']


def test_dated_job_grade_is_filled_without_offer_or_manual_replacement():
    row=referral_row();row['values'].update(核算月份=MONTH,职级='',职位='')
    h=proof('zt1','zt2');h.update(jobLevelName='P1-3',positionName='仓库员工')
    enrich(row,{'zt1':[h]},ROLE_FIELDS)
    assert row['values']['职级']=='P1-3' and row['values']['职位']=='仓库员工'
    row['values']['职级']='P2-1';row['edits']=[{'field':'职级','value':'P2-1'}]
    enrich(row,{'zt1':[h]},ROLE_FIELDS)
    assert row['values']['职级']=='P2-1'


def test_overseas_only_sync_completes_recipient_facts_in_the_same_action(tmp_path,monkeypatch):
    from test_recruitment_recipient_sync import employment_snapshot
    store=DraftStore(tmp_path);calls=[]
    def monthly(month,**kwargs):
        value=snapshot(month);value['offers'][0].update(招聘渠道='招聘网站',其他渠道='');return value
    def domestic(numbers,**kwargs):
        calls.append(('domestic',numbers))
        return beisen._with_coverage({'version':1,'queriedAt':'2026-10-26T12:00:00','employmentOnly':True,
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'candidateHistories':[],
            'recipientHistories':[],'offers':[],'forms':[],'requirements':[]})
    def foreign(month,numbers,**kwargs):calls.append(('overseas',numbers));return employment_snapshot()
    monkeypatch.setattr(overseas,'fetch',monthly)
    monkeypatch.setattr(beisen,'fetch_employment',domestic)
    monkeypatch.setattr(overseas,'fetch_employment',foreign)
    jobs.start(store,MONTH,0,overseas_only=True)
    for _ in range(500):
        job=jobs.read_status(store,MONTH)
        if job['status'] not in {'running','cancelling'}:break
        time.sleep(.01)
    assert job['status']=='complete',job
    assert job['coverageGaps']==[]
    assert calls==[('domestic',['zt2']),('overseas',['zt2'])]
    state=store.read(MONTH)
    assert len(state['rows'])==1
    assert not any('招聘负责人：' in issue for node in state['rows'][0]['calculation']['recruitment']['nodes'] for issue in node['issues'])


def test_saved_channel_note_lookup_is_connected_and_not_repeated(tmp_path,monkeypatch):
    from test_recruitment_intake_fixes import _api_payload, ROSTER
    from test_recruitment_drafts import book
    store=DraftStore(tmp_path)
    state=store.ingest(202606,[('roster.xlsx',book(ROSTER,[['甲','zt1','2026-06-01','正式','EHR入职','','P3']]))],0)
    payload=_api_payload('zt1','OF1');payload['candidateHistories'][0]['entryDate']='2026-06-01'
    payload['offers'][0].update(entryDate='2026-06-01',modifiedTime='2026-06-01T12:00:00')
    payload['offers'][0]['customProperties'][beisen.CHANNEL]=10
    state=store.save_beisen_snapshot(202606,state['revision'],payload);calls=[]
    def notes(saved,checked,**kwargs):
        calls.append(saved)
        return {'version':1,'queriedAt':'2026-10-26T12:00:00','channelDetailsOnly':True,
                'channelDetailsCheckedOfferIds':['OF1'],'channelChecks':[{'offerId':'OF1','status':'已取得备注'}],
                'candidateHistories':saved['candidateHistories'],'recipientHistories':[],'forms':[],'requirements':[],
                'offers':[{'objectId':'OF1','entryDate':'2026-06-01','approvalStatus':2,'remarks':'招聘网站'}]}
    monkeypatch.setattr(beisen,'fetch_channel_details',notes)
    after=jobs.repair_channel_notes(store,202606,state,lambda **k:None)
    assert len(calls)==1 and after['rows'][0]['values']['招聘渠道备注']=='招聘网站'
    assert after['rows'][0]['values']['招聘渠道']=='其他'
    assert after['rows'][0]['calculation']['recruitment']['total']==state['rows'][0]['calculation']['recruitment']['total']==0
    again=jobs.repair_channel_notes(store,202606,after,lambda **k:None)
    assert len(calls)==1 and again['revision']==after['revision']


def test_missing_manager_field_cannot_prove_a_root_node():
    row=referral_row();h=proof('zt1','');h['lineManagerProvided']='0'
    result=evidence(row,{'zt1':[h]})
    assert not result['complete'] and result['pending']


def test_empty_targeted_query_is_valid_but_does_not_prove_monthly_roster_coverage(tmp_path):
    store=DraftStore(tmp_path)
    domestic=beisen._with_coverage({'version':1,'queriedAt':'2026-10-26T12:00:00','employmentOnly':True,
        'requestedJobNumbers':[],'requestedRecipientJobNumbers':['zt1'],'candidateHistories':[],
        'recipientHistories':[],'offers':[],'forms':[],'requirements':[]})
    state=store.save_beisen_snapshot(MONTH,0,domestic)
    foreign={'version':1,'month':MONTH,'queriedAt':'2026-10-26T12:00:00','employmentOnly':True,
        'requestedJobNumbers':['zt1'],'requestedOfferCodes':[],'missingOfferCodes':[],
        'employmentHistory':[],'roster':[],'offers':[]}
    state=store.save_overseas_snapshot(MONTH,state['revision'],foreign)
    offer={**foreign,'employmentOnly':False,'offerOnly':True,'requestedJobNumbers':[],
           'employmentHistory':[],'requestedOfferCodes':['OF1'],'missingOfferCodes':['OF1']}
    state=store.save_overseas_snapshot(MONTH,state['revision'],offer)
    assert not [t for t in state['todos'] if t['kind']=='source_unrecognized']
    assert any(t['kind']=='coverage' for t in state['todos'])
    assert state['sources'][-1]['snapshotVersion']>state['sources'][-2]['snapshotVersion']
    state=store.save_overseas_snapshot(MONTH,state['revision'],snapshot(MONTH))
    assert len(state['rows'])==1 and not state['sources'][-1]['comparisonOnly']
    assert not any(t['kind']=='coverage' for t in state['todos'])
