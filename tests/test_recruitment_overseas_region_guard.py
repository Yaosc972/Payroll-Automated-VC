from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_overseas as overseas
from bonus_platform.engine.recruitment_awards import calculate_draft
from bonus_platform.engine.recruitment_drafts import _empty, assemble
from test_recruitment_overseas import snapshot


def history(**changes):
    return dict(empNo='zt1', recordId='historical-employment',
                entryDate='2026-08-01', startDate='2026-08-01', endDate='2026-08-31',
                employmentType='0', employmentStatus='0', employeeStatus='3',
                jobLevelName='P1-3', positionName='专员', deptName='美国历史部门',
                **changes)


def calculate(records=None, *, legacy=False):
    payload = snapshot()
    payload['offers'][0].update(招聘渠道='招聘网站', 其他渠道='')
    if not legacy:
        payload['employmentHistory'] = [{'empNo': 'zt1', 'records': records or []}]
    parsed = overseas.parsed_snapshot(payload, 'synthetic-source')
    state = _empty(202608)
    state['sources'] = [dict(id='synthetic-source', forMonth=202608, active=True,
                             kind='overseas_api', dataDigest='synthetic',
                             roleCounts={'roster': 1}, recordCount=len(parsed['records']))]
    state = assemble(202608, parsed['records'], state)
    calculate_draft(state)
    return state['rows'][0], parsed


@pytest.mark.parametrize('records', [
    [history()],
    [history(), {**history(), 'recordId': 'overlap', 'deptName': '另一个历史部门'}],
    [{**history(), 'deptName': ''}],
    [],
])
def test_unproven_historical_region_never_borrows_current_german_location(records):
    row, parsed = calculate(records)
    result = row['calculation']['recruitment']
    assert not row['values'].get('工作地')
    assert not any(row['values'].get(f) for f in ('二级组织', '三级组织', '四级组织', '五级组织'))
    assert result['currency'] == ''
    assert result['countryBasis'] == ''
    assert '标准币种对应地区待核' in result['issues']
    assert all(t['status'] == '待核对' for t in result['nodes'])
    assert result['nodes'] or result['total'] is None
    assert parsed['records'][0]['rawValues']['工作地'] == '德国'


def test_unique_historical_workplace_can_prove_currency_after_department_change():
    row, parsed = calculate([{**history(), 'workPlacePathName': '美国/加利福尼亚'}])
    result = row['calculation']['recruitment']
    assert row['values']['工作地'] == '美国/加利福尼亚'
    assert result['currency'] == '美元'
    assert result['countryBasis'] == '美国/加利福尼亚'
    assert '标准币种对应地区待核' not in result['issues']
    assert parsed['records'][0]['rawValues']['工作地'] == '德国'


def test_conflicting_historical_workplaces_stay_pending_even_when_department_matches():
    records = [{**history(), 'deptName': '测试仓', 'workPlacePathName': '德国'},
               {**history(), 'deptName': '测试仓', 'recordId': 'overlap', 'workPlacePathName': '美国'}]
    row, _ = calculate(records)
    assert row['calculation']['recruitment']['currency'] == ''
    assert '标准币种对应地区待核' in row['calculation']['recruitment']['issues']


@pytest.mark.parametrize('legacy', [False, True])
def test_same_department_and_legacy_snapshot_keep_existing_region(legacy):
    row, _ = calculate([{**history(), 'deptName': '测试仓'}], legacy=legacy)
    assert row['values']['工作地'] == '德国'
    assert row['calculation']['recruitment']['currency'] == '欧元'


def test_historical_workplace_supersedes_current_hierarchy_without_mutating_input():
    payload = snapshot()
    payload['employmentHistory'] = [{'empNo': 'zt1', 'records': [
        {**history(), 'deptName': '测试仓', 'workPlacePathName': '美国'}]}]
    before = deepcopy(payload)
    parsed = overseas.parsed_snapshot(payload, 'synthetic-source')
    assert payload == before
    values = parsed['records'][0]['values']
    assert values['工作地'] == '美国'
    assert not any(values.get(f) for f in ('二级组织', '三级组织', '四级组织', '五级组织'))


@pytest.mark.parametrize('path,currency',[
    ('纵腾网络/FBU仓储事业部/美洲区/加州区/洛杉矶25号仓/包装组','美元'),
    ('纵腾网络/FBU仓储事业部/欧洲区/德国区/杜塞尔多夫20号仓/包装组','欧元'),
])
def test_effective_full_organization_proves_country_when_workplace_only_says_non_china(path,currency):
    row,parsed=calculate([{**history(), 'deptName':'包装组','workPlacePathName':'非中国','orgPathName':path}])
    assert row['calculation']['recruitment']['currency']==currency
    assert '标准币种对应地区待核' not in row['calculation']['recruitment']['issues']
    assert row['values']['二级组织']=='FBU仓储事业部'
    assert parsed['records'][0]['rawValues']['工作地']=='德国'


@pytest.mark.parametrize('case',['overlap','future','secondary','wrong-entry','wrong-leaf'])
def test_unproven_organization_path_cannot_supply_a_historical_country(case):
    record={**history(),'deptName':'包装组','workPlacePathName':'非中国',
            'orgPathName':'纵腾网络/FBU仓储事业部/美洲区/加州区/洛杉矶25号仓/包装组'}
    records=[record]
    if case=='overlap':records.append({**record,'recordId':'other','orgPathName':'纵腾网络/FBU仓储事业部/欧洲区/德国区/测试仓/包装组'})
    elif case=='future':record.update(startDate='2026-09-01',endDate='9999-12-31')
    elif case=='secondary':record['employmentType']='1'
    elif case=='wrong-entry':record['entryDate']='2026-07-01'
    elif case=='wrong-leaf':record['orgPathName']='纵腾网络/德国区/另一个部门'
    row,_=calculate(records)
    assert row['calculation']['recruitment']['currency']==''
    assert '标准币种对应地区待核' in row['calculation']['recruitment']['issues']


def test_prepare_fills_new_hire_country_from_targeted_employment_query(tmp_path,monkeypatch):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine.recruitment_prepare import repair_employments
    store=DraftStore(tmp_path);payload=snapshot(202609)
    payload['offers'][0].update(招聘渠道='招聘网站',其他渠道='')
    record={**history(),'entryDate':'2026-09-01','startDate':'2026-09-01','endDate':'9999-12-31',
            'employeeInfoId':'person-1','deptName':'包装组','workPlacePathName':'非中国'}
    payload['employmentHistory']=[{'empNo':'zt1','records':[record]}]
    before=store.save_overseas_snapshot(202609,0,payload)
    assert before['rows'][0]['calculation']['recruitment']['currency']==''
    calls=[]
    def fetch(month,numbers,**kwargs):
        calls.append((month,numbers));proof=deepcopy(payload)
        proof.update(employmentOnly=True,requestedJobNumbers=numbers,offers=[],queriedAt='2026-10-26T13:00:00+08:00')
        proof['roster'][0]['scope']='lookup'
        proof['employmentHistory'][0]['records'][0]['orgPathName']='纵腾网络/FBU仓储事业部/欧洲区/德国区/测试仓/包装组'
        return proof
    monkeypatch.setattr(overseas,'fetch_employment',fetch)
    after=repair_employments(store,202609,before,lambda **values:None)
    assert calls==[(202609,['zt1'])]
    assert after['rows'][0]['calculation']['recruitment']['currency']=='欧元'
    assert after['rows'][0]['id']==before['rows'][0]['id'] and after['edits']==before['edits']
