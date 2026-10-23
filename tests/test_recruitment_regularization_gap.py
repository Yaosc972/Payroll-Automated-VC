from copy import deepcopy
from datetime import date

import pytest

from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_employment import status_from_timeline
from bonus_platform.engine import recruitment_work_items as work
from test_recruitment_attention import state_for
from test_recruitment_awards import person


def referrer_without_regularization(**values):
    row=person(hire='2026-08-01',标签分类='国内',工作地='中国大陆',二级组织='国内组织',
               奖金地区类型='国内发展中国家',推荐人入职日期='',推荐人人员状态='',推荐人转正日期='')
    row['values'].update(values)
    row['edits']=[]
    row['employmentTimelines']={'推荐人':[{
        'provider':'beisen','userID':'synthetic-referrer','entryDate':'2020-01-01',
        'startDate':'2020-01-01','stopDate':'9999-12-31','approvalStatus':4,
        'serviceType':0,'employeeStatus':'3','regularizationDate':None,
        'lastWorkDate':'','queriedAt':'2026-10-22T12:00:00'}]}
    return row


def test_missing_domestic_regularization_identifies_the_actual_award_gap():
    row=referrer_without_regularization();before=deepcopy(row)
    node=next(n for n in award(row,'referral',202608)['nodes'] if n['dueMonth']==202608)
    assert node['status']=='本月到期'
    assert not node['issues']
    assert not any('任职日期待核' in issue for issue in node['issues'])
    assert not node.get('eligibilityReasons')
    assert row==before


def test_regularization_gap_projects_the_actual_input_in_final_work_item_detail():
    state=state_for([referrer_without_regularization()],[],202608)
    assert not any(i['key']=='recipient' for i in work.project(state,project(state)))


@pytest.mark.parametrize('manual',[False,True])
def test_trusted_static_regularization_keeps_the_existing_fallback(manual):
    row=referrer_without_regularization(推荐人入职日期='2020-01-01',推荐人人员状态='正式',推荐人转正日期='2020-07-01')
    if manual:row['edits']=[{'field':'推荐人转正日期','value':'2020-07-01'}]
    assert status_from_timeline(row,'推荐人',date(2026,8,31),formal=True) is None
    node=next(n for n in award(row,'referral',202608)['nodes'] if n['dueMonth']==202608)
    assert node['status']=='本月到期'
    assert not node['issues']


def test_unusable_static_regularization_does_not_hide_the_missing_api_date():
    row=referrer_without_regularization(推荐人人员状态='正式',推荐人转正日期='2019-12-31')
    assert status_from_timeline(row,'推荐人',date(2026,8,31),formal=True)=='转正日期待核对'
