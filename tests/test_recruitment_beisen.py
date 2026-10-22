from copy import deepcopy
import pytest
from bonus_platform.engine.recruitment_beisen import parsed_snapshot
from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from test_recruitment_drafts import book


def snapshot():
    common={'userID':10,'jobNumber':'zt1','lUOffer':'offer1','approvalStatus':4,'serviceType':0}
    return {'version':1,'queriedAt':'2026-09-16T12:00:00','scopeJobNumbers':['zt1'],
        'candidateHistories':[{**common,'startDate':'2026-04-01','stopDate':'2026-06-30','entryDate':'2026-04-01','employType':2},
                              {**common,'startDate':'2026-07-01','stopDate':'9999-12-31','entryDate':'2026-07-01','employType':0}],
        'offers':[{'objectId':'offer1','name':'甲','entryDate':'2026-04-01','approvalStatus':'2','employmentForm':'intern','customProperties':{}}],
        'forms':[{'fields':{'OId':'intern','Name':'实习生日薪'}}], 'requirements':[],'recipientHistories':[]}


def test_continuity_requires_adjacent_same_employee_and_same_offer():
    p=snapshot();assert len([r for r in parsed_snapshot(p,'a')['records'] if r['role']=='employment_link'])==1
    for field,value in [('userID',11),('lUOffer','other'),('stopDate','2026-06-28')]:
        changed=deepcopy(p);changed['candidateHistories'][0][field]=value
        assert not any(r['role']=='employment_link' for r in parsed_snapshot(changed,'a')['records'])


def test_unknown_options_do_not_default_to_eligible_category():
    p=snapshot();p['offers'][0]['customProperties']['extQ20210635_109025_2041445622']='999'
    out=parsed_snapshot(p,'a');assert out['warnings'][0]['code']=='999'
    assert out['records'][0]['values']['招聘渠道']==''


def test_virtual_roster_not_a_new_recruitment_but_explicit_supplement_retained(tmp_path):
    store=DraftStore(tmp_path)
    headers=['姓名','工号','入职日期','人员状态','人员来源','是否虚拟员工']
    state=store.ingest(202607,[('roster.xlsx',book(headers,[['虚拟','zt9','2026-07-01','正式','EHR入职','是'],['真人','zt1','2026-07-01','正式','EHR入职','否']]))],0)
    assert [r['values']['工号'] for r in state['rows']]==['zt1']
    state=store.ingest(202607,[('supplement.xlsx',book(['体系外人员编号','姓名','工号','入职日期'],[['a','有明确依据','zt9','2026-07-01']]))],state['revision'])
    assert len(state['rows'])==2


def test_snapshot_rebuild_keeps_user_edits_and_atomic_revision(tmp_path):
    store=DraftStore(tmp_path);headers=['姓名','工号','入职日期','人员状态','人员来源']
    before=store.ingest(202607,[('roster.xlsx',book(headers,[['甲','zt1','2026-07-01','正式','EHR入职']]))],0)
    with pytest.raises(DraftConflict):store.save_beisen_snapshot(202607,0,snapshot())
    assert store.read(202607)['revision']==before['revision']
    state=store.save_beisen_snapshot(202607,before['revision'],snapshot())
    assert len(state['rows'])==1
    assert state['rows'][0]['values']['入职日期']=='2026-04-01'
    assert state['rows'][0]['rule']['version']=='legacy'
    again=store.save_beisen_snapshot(202607,state['revision'],snapshot())
    assert again['revision']==state['revision']


def test_sync_does_not_replace_user_reviewed_employment(tmp_path):
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[("roster.xlsx",book(["姓名","工号","入职日期","人员状态","人员来源"],[["甲","zt1","2026-07-01","正式","EHR入职"]]))],0)
    row=state["rows"][0]
    state["edits"].append({"rowId":row["id"],"field":"任职说明","value":"已人工核对，保留当前任职","before":None,"active":True})
    store._write(store._folder(202607)/"draft.json",state)
    result=store.save_beisen_snapshot(202607,state["revision"],snapshot())
    same=next(r for r in result["rows"] if r["id"]==row["id"])
    assert same["values"]["入职日期"]=="2026-07-01"
    assert same["values"]["任职说明"]=="已人工核对，保留当前任职"


def test_api_sync_is_scoped_to_existing_domestic_people(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bonus_platform import recruitment_draft_api as api
    from bonus_platform.engine import recruitment_beisen as adapter
    store=DraftStore(tmp_path);monkeypatch.setattr(api,'store',store)
    state=store.ingest(202607,[('roster.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源'],[['甲','zt1','2026-07-01','正式','EHR入职'],['海外','ov1','2026-07-02','正式','OEHR入职']]))],0)
    calls=[]
    def fetch(numbers):calls.append(numbers);return snapshot()
    monkeypatch.setattr(adapter,'fetch',fetch)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    assert client.post('/api/recruitment/drafts/202607/sync-domestic',json={'revision':0}).status_code==409
    assert not calls
    response=client.post('/api/recruitment/drafts/202607/sync-domestic',json={'revision':state['revision']})
    assert response.status_code==200
    assert calls==[['zt1']]
    assert any(s.get('kind')=='beisen' for s in response.json()['sources'])


def test_historical_conversion_does_not_create_unlisted_monthly_person(tmp_path):
    store=DraftStore(tmp_path)
    state=store.ingest(202608,[("roster.xlsx",book(["姓名","工号","入职日期","人员状态","人员来源"],[["甲","zt1","2026-07-01","正式","EHR入职"]]))],0)
    assert not state["rows"]
    result=store.save_beisen_snapshot(202608,state["revision"],snapshot())
    assert not result["rows"]
