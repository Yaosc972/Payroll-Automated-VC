from datetime import date

import pytest

from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_employment import status_from_timeline
from test_recruitment_awards import person


def domestic_row(prefix='', **history_values):
    row=person(hire='2026-08-01',标签分类='国内',工作地='中国大陆',
               二级组织='国内组织',奖金地区类型='国内发展中国家',推荐人工号='',推荐人姓名='')
    row['edits']=[]
    entry=row['values'][prefix+'入职日期']
    history={'provider':'beisen','userID':'synthetic','entryDate':entry,
             'startDate':entry,'stopDate':'9999-12-31','approvalStatus':4,
             'serviceType':0,'employeeStatus':'3','lastWorkDate':'',
             'queriedAt':'2026-10-22T12:00:00'}
    history.update(history_values)
    row['employmentTimelines']={prefix:[history]}
    return row


def august_node(row):
    return next(n for n in award(row,'recruitment',202608)['nodes'] if n['dueMonth']==202608)


@pytest.mark.parametrize('prefix',['','招聘负责人'])
@pytest.mark.parametrize('status',['unexpected','',None,'1','4'])
def test_explicit_unknown_domestic_status_cannot_qualify_an_award(prefix,status):
    row=domestic_row(prefix,employeeStatus=status)
    node=august_node(row)
    assert node['status']=='待核对'
    assert any('任职记录状态待核对' in issue for issue in node['issues'])


@pytest.mark.parametrize('prefix',['','招聘负责人'])
def test_award_after_domestic_capture_date_stays_pending(prefix):
    row=domestic_row(prefix,queriedAt='2026-08-15T12:00:00')
    node=august_node(row)
    assert node['status']=='待核对'
    assert any('适用日期晚于资料采集日期' in issue for issue in node['issues'])


def test_domestic_leaver_without_exit_date_does_not_prove_historical_service():
    node=august_node(domestic_row(employeeStatus='8'))
    assert node['status']=='待核对'
    assert any('任职记录状态待核对' in issue for issue in node['issues'])


@pytest.mark.parametrize('status',['2',3,'8'])
def test_known_domestic_status_preserves_service_within_dated_segment(status):
    row=domestic_row(employeeStatus=status,lastWorkDate='2026-08-31',stopDate='2026-08-31')
    assert status_from_timeline(row,'',date(2026,8,31))==''
    assert august_node(row)['status']=='本月到期'


def test_legacy_domestic_history_without_status_field_remains_usable():
    row=domestic_row()
    del row['employmentTimelines'][''][0]['employeeStatus']
    row['values']['人员状态']=''
    assert august_node(row)['status']=='本月到期'


def test_same_day_capture_proves_only_through_that_day():
    row=domestic_row(queriedAt='2026-08-31T00:00:00')
    assert august_node(row)['status']=='本月到期'


def test_reviewed_manual_status_can_supersede_unusable_api_observation():
    row=domestic_row(employeeStatus='unexpected',queriedAt='2026-08-15T12:00:00')
    row['edits']=[{'field':'人员状态','value':'正式'}]
    assert august_node(row)['status']=='本月到期'
