from copy import deepcopy
from datetime import date

import pytest

from bonus_platform.engine import recruitment_domestic as domestic
from bonus_platform.engine import recruitment_overseas as overseas
from bonus_platform.engine.recruitment_employment import index_histories, enrich, status_from_timeline
from test_recruitment_activities import activities, base, create
from test_recruitment_adoption import fill_month, snapshot as files_snapshot
from test_recruitment_domestic_monthly import snapshot as domestic_snapshot
from test_recruitment_overseas import snapshot as overseas_snapshot


def history(number='zt1', **changes):
    return dict(empNo=number, employeeInfoId='employee-1', recordId='record-1',
                startDate='2026/08/01', endDate='2026/08/31', entryDate='2026/08/01',
                lastWorkDay='', employmentType='0', employmentStatus='1', employeeStatus='2',
                businessType='1', businessTypeName='入职', **changes)


def with_history(records=None):
    value=overseas_snapshot(202608)
    value['employmentHistory']=[{'empNo':'zt1','records':records if records is not None else [history()]}]
    return value


def overseas_row(payload):
    parsed=overseas.parsed_snapshot(payload,'oehr-source')
    row={'values':{'工号':'zt1','入职日期':'2026-08-01','标签分类':'海外'},
         'edits':[],'sources':[],'provenance':{},'conflicts':[]}
    enrich(row,index_histories(parsed['records']),[])
    return row


def test_overseas_history_snapshot_is_scoped_minimized_and_query_complete():
    value=with_history();value['employmentHistory'][0]['records'][0]['privateInterview']='do not retain'
    saved=overseas.validate_snapshot(value,202608)
    assert saved['employmentHistory'][0]['records'][0]['startDate']=='2026-08-01'
    assert 'privateInterview' not in saved['employmentHistory'][0]['records'][0]
    for changed in [dict(empNo='not-requested'),dict(records=[history(number='someone-else')]),
                    dict(records=[{**history(),'endDate':'2026/07/01'}])]:
        invalid=deepcopy(value);invalid['employmentHistory'][0].update(changed)
        with pytest.raises(ValueError):overseas.validate_snapshot(invalid,202608)
    assert 'employmentHistory' not in overseas.validate_snapshot(overseas_snapshot(),202608)


def test_overseas_history_proves_past_service_including_terminated_segments():
    records=[history(),{**history(),'recordId':'exit','startDate':'2026/09/01',
                       'endDate':'9999/12/31','lastWorkDay':'2026/08/31','employeeStatus':'8','businessType':'4'}]
    row=overseas_row(with_history(records))
    assert status_from_timeline(row,'',date(2026,8,31))==''
    assert status_from_timeline(row,'',date(2026,9,1))=='适用日期已不在职'
    assert '转正日期' not in row['values']
    assert row['values']['最后工作日']=='2026-08-31'


def test_overlapping_overseas_status_and_missing_past_interval_stay_pending():
    records=[history(),{**history(),'recordId':'formal','employeeStatus':'3'}]
    row=overseas_row(with_history(records))
    assert status_from_timeline(row,'',date(2026,8,31),formal=True)=='任职记录在适用日期存在冲突'
    assert status_from_timeline(row,'',date(2026,9,1))=='缺少适用日期的任职记录'
    assert status_from_timeline(row,'',date(2027,8,1))=='适用日期晚于资料采集日期'
    row['edits']=[{'field':'人员状态','value':'正式'}]
    assert status_from_timeline(row,'',date(2026,8,31),formal=True) is None


def test_empty_api_dates_remain_evidence_and_create_a_review_instead_of_guessing_open_ended():
    payload=with_history([{**history(),'endDate':''}])
    saved=overseas.validate_snapshot(payload,202608)
    assert saved['employmentHistory'][0]['records'][0]['endDate']==''
    assert status_from_timeline(overseas_row(saved),'',date(2026,8,31))=='任职记录生效日期待核对'


@pytest.mark.parametrize('provider',['oehr','beisen'])
def test_recipient_current_rehire_date_does_not_hide_valid_historical_employment(provider):
    fact={**history(),'provider':provider,'queriedAt':'2026-10-22','entryDate':'2026-08-01',
          'startDate':'2026-08-01','endDate':'2026-08-31','stopDate':'2026-08-31',
          'approvalStatus':4,'serviceType':0,'userID':1}
    row={'values':{'招聘负责人入职日期':'2026-09-01'},'edits':[],
         'recipientSourceRegions':{'招聘负责人':'海外' if provider=='oehr' else '国内'},
         'employmentTimelines':{'招聘负责人':[fact]}}
    assert status_from_timeline(row,'招聘负责人',date(2026,8,15))==''


def test_overseas_rehire_does_not_borrow_current_employment_and_provider_does_not_replace_history():
    value=with_history([history()]);row=overseas_row(value)
    row['values']['入职日期']='2025-01-01'
    assert status_from_timeline(row,'',date(2026,8,31))=='缺少本次任职的日期记录'
    parsed=overseas.parsed_snapshot(value,'oehr-source')['records']
    parsed.append({'role':'employment_history','values':{'工号':'zt1'},'ref':{'sourceId':'beisen-source'},
                   'apiEvidence':{'queriedAt':'2026-11-01','history':{'jobNumber':'zt1'}}})
    index=index_histories(parsed)
    assert len(index['zt1'])==2
    row=overseas_row(value);enrich(row,index,[])
    assert status_from_timeline(row,'',date(2026,8,31))==''


def test_domestic_monthly_scope_includes_historical_candidates_and_recipients():
    state={'rows':[{'values':{'标签分类':'国内','工号':'zt-old','招聘负责人工号':'ZT-OWNER'}},
                   {'values':{'标签分类':'海外','工号':'zt-overseas','推荐人工号':'ZT-REF'}}]}
    scope=domestic.scope(state)
    assert scope['job_numbers']==['zt-old']
    assert scope['recipient_numbers']==['zt-owner','zt-ref']


def test_carry_then_both_syncs_apply_in_new_activity_and_leave_parent_unchanged(activities):
    client,store=activities;parent=create(client)
    state=fill_month(client,base(parent),202607,'历史人员')
    assert client.post(base(parent)+'/confirm-month',json={'revision':state['revision'],'coverageConfirmed':True}).status_code==200
    protected=files_snapshot(store.activity_root/parent['id'])
    child=create(client,month=202608,opening={'activityId':parent['id'],'revision':state['revision']})
    # Use the activity context through its existing API, not another month's store.
    from bonus_platform.engine.recruitment_activities import ACTIVITY
    token=ACTIVITY.set(child['id'])
    try:
        current=store.read(202608)
        assert current['monthlyWorkflow'] is True
        domestic_value=domestic_snapshot(202608);domestic_value['roster'][0]['工号']='zt101'
        for item in domestic_value['candidateHistories']:item['jobNumber']='zt101'
        current=store.save_beisen_snapshot(202608,current['revision'],domestic_value)
        current=store.save_overseas_snapshot(202608,current['revision'],with_history())
        assert not any(s.get('comparisonOnly') for s in current['sources'] if s.get('forMonth')==202608)
        assert {'zt101','zt1'}<={r['values'].get('工号') for r in current['rows']}
        assert any(r['values'].get('姓名')=='历史人员' for r in current['rows'])
    finally:ACTIVITY.reset(token)
    assert files_snapshot(store.activity_root/parent['id'])==protected


def workflow_snapshots(month=202607):
    domestic_value=domestic_snapshot(month)
    for key in ('roster','candidateHistories','recipientHistories','offers','forms','requirements','scopeJobNumbers'):
        domestic_value[key]=[]
    foreign=overseas_snapshot(month);template=deepcopy(foreign['roster'][0]['data']);offer=deepcopy(foreign['offers'][0])
    foreign.update(roster=[],offers=[],employmentHistory=[])
    entry=f'{month//100}-{month%100:02d}-01'
    for i,(name,country) in enumerate([('验收甲','德国'),('验收乙','美国')],1):
        number=f'ov10{i}';code=f'OF{i}'
        raw={**template,'姓名':name,'工号':number,'offer流程编号':code,'二级部门':country,'三级部门':'','四级部门':'',
             '五级部门':'测试仓','办公地址':country,'人员状态':'正式','入职日期':entry}
        foreign['roster'].append({'scope':'month','data':raw})
        foreign['offers'].append({**offer,'姓名':name,'offer编码':code,'招聘负责人工号':'ov900',
            '招聘负责人':'验收负责人','招聘渠道':'Boss直聘','其他渠道':'','招聘启动日期':f'{month//100}-{month%100-2:02d}-20'})
    foreign['roster'].append({'scope':'lookup','data':{**template,'姓名':'验收负责人','工号':'ov900',
        'offer流程编号':'','入职日期':'2020-01-01','人员状态':'正式','五级部门':'测试仓'}})
    for rec in foreign['roster']:
        raw=rec['data']
        foreign['employmentHistory'].append({'empNo':raw['工号'],'records':[{**history(raw['工号']),
            'entryDate':raw['入职日期'],'startDate':raw['入职日期'],'endDate':'9999-12-31',
            'employeeInfoId':raw['工号'],'recordId':raw['工号']+'-record','employmentStatus':'0',
            'employeeStatus':'3','deptName':'测试仓','jobLevelName':raw['职级'],'positionName':raw['职位']}]})
    return domestic_value,foreign


def test_one_click_then_offline_approval_updates_details_and_keeps_original_snapshot(activities,monkeypatch):
    from pathlib import Path
    import time
    client,store=activities;activity=create(client,month=202607);url=base(activity)
    domestic_value,foreign=workflow_snapshots()
    monkeypatch.setattr(domestic,'fetch',lambda *a,**k:deepcopy(domestic_value))
    monkeypatch.setattr(overseas,'fetch',lambda *a,**k:deepcopy(foreign))
    assert client.post(url+'/sync-monthly',json={'revision':0}).status_code==200
    for _ in range(300):
        job=client.get(url+'/prepare').json()
        if job['status']!='running':break
        time.sleep(.01)
    assert job['status']=='complete',job
    state=client.get(url).json()
    assert not any(t['kind']=='source_unrecognized' for t in state['todos'])
    first_source=state['sources'][-1]['id']
    state=client.post(url+'/opening-empty',json={'revision':state['revision'],'confirmed':True}).json()
    response=client.post(url+'/sources',data={'revision':state['revision'],'periodConfirmed':'true'},
        files=[('files',('周期审批.pdf',(Path(__file__).parent/'fixtures/recruitment-workflow-approval.pdf').read_bytes()))])
    assert response.status_code==200,response.text
    state=response.json();items=state['approvalAdjustments']['items']
    ready=[i['id'] for i in items if i['status']=='ready']
    assert len(ready)==2,items
    preview=client.post(url+'/approval-adjustments/preview',json={'revision':state['revision'],'itemIds':ready})
    assert preview.status_code==200,preview.text
    result=client.post(url+'/previews/'+preview.json()['id']+'/apply',json={'revision':state['revision']})
    assert result.status_code==200,result.text
    updated=result.json()
    assert all(r['values']['周期剔除天数']==5 for r in updated['rows'])
    assert any(s['id']==first_source for s in updated['sources'])
    assert client.get(url+'/monthly/export',params={'revision':updated['revision']}).status_code==200
