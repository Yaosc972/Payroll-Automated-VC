from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import award, cycle
from test_recruitment_awards import person


def confirmed_values(*, snapshot=False):
    values = {
        '招聘启动日期': '2026-02-26', '入职日期': '2026-02-25',
        '周期剔除天数': 0, '标签分类': '国内',
        '负周期确认启动日期': '2026-02-26', '负周期确认入职日期': '2026-02-25',
        '负周期确认依据': '用户确认本次任职按原始负一天核算，保留异常提示。',
    }
    if snapshot:
        values['负周期确认剔除天数'] = 0
    return values


def test_confirmed_negative_day_calculates_with_nonblocking_warning():
    result, issues = cycle(confirmed_values(), 42, 'legacy')
    assert issues == []
    assert result['actualDays'] == -1
    assert result['factor'] == 1.3
    assert '按原日期核算' in result['warning']
    row = person('2026-02-25', **{k: v for k, v in confirmed_values().items() if k != '入职日期'})
    row['values'].update(工作地='中国大陆', 职级='P1-2', 招聘渠道='内推', 转正日期='2026-07-02')
    result = award(row, 'recruitment', 202607)
    assert result['total'] == 78
    assert result['currentAmount'] == 39
    assert not result['issues']
    assert any('按原日期核算' in reason for reason in result['reasons'])


@pytest.mark.parametrize('updates', [
    {'负周期确认依据': ''}, {'负周期确认启动日期': ''}, {'负周期确认入职日期': ''},
    {'招聘启动日期': '2026-02-27'}, {'入职日期': '2026-02-24'},
    {'周期剔除天数': 1}, {'周期剔除天数': -1},
])
def test_unconfirmed_or_changed_negative_period_still_blocks(updates):
    values = {**confirmed_values(), **updates}
    result, issues = cycle(values, 42, 'legacy')
    assert result['factor'] is None
    assert issues


def test_old_confirmation_does_not_enable_new_policy_without_exclusion_snapshot():
    values = confirmed_values()
    result, issues = cycle(values, 42, '2026-07')
    assert result['factor'] is None and issues


@pytest.mark.parametrize('version', ['legacy', '2026-07'])
@pytest.mark.parametrize('hire,raw', [('2026-07-14', -1), ('2026-07-13', -2)])
@pytest.mark.parametrize('exclusion', [0, 2.5])
def test_confirmed_original_dates_calculate_both_rule_versions(version, hire, raw, exclusion):
    values = {
        **confirmed_values(snapshot=True), '标签分类': '海外',
        '招聘启动日期': '2026-07-15', '入职日期': hire, '周期剔除天数': exclusion,
        '负周期确认启动日期': '2026-07-15', '负周期确认入职日期': hire,
        '负周期确认剔除天数': str(exclusion),
        '周期剔除依据': '现有审批认可的剔除天数',
    }
    before = deepcopy(values)
    result, issues = cycle(values, 42, version)
    assert issues == []
    assert result['actualDays'] == raw - exclusion
    assert result['exclusionDays'] == exclusion
    assert result['factor'] == 1.3
    assert '2026-07-15' in result['warning'] and hire in result['warning']
    assert result['confirmationBasis'] == values['负周期确认依据']
    assert values == before


@pytest.mark.parametrize('version', ['legacy', '2026-07'])
@pytest.mark.parametrize('updates', [
    {'负周期确认依据': ''}, {'负周期确认启动日期': ''}, {'负周期确认入职日期': ''},
    {'负周期确认剔除天数': ''}, {'负周期确认剔除天数': 1},
    {'招聘启动日期': '2026-02-27'}, {'入职日期': '2026-02-24'}, {'周期剔除天数': 1},
])
def test_original_date_confirmation_invalidates_when_snapshot_changes(version, updates):
    result, issues = cycle({**confirmed_values(snapshot=True), **updates}, 42, version)
    assert result['factor'] is None
    assert issues


@pytest.mark.parametrize('version', ['legacy', '2026-07'])
@pytest.mark.parametrize('exclusion', ['', -1, 'NaN', 'Infinity', 'not-a-number', '1e10000'])
def test_confirmation_cannot_bypass_invalid_exclusion(version, exclusion):
    values = {**confirmed_values(snapshot=True), '周期剔除天数': exclusion,
              '负周期确认剔除天数': exclusion}
    result, issues = cycle(values, 42, version)
    assert result['factor'] is None
    assert issues


@pytest.mark.parametrize('standard', [None, '', 0, -1, 'NaN', 'Infinity', '1e10000'])
def test_confirmation_cannot_bypass_missing_or_invalid_standard(standard):
    result, issues = cycle(confirmed_values(snapshot=True), standard, '2026-07')
    assert result['factor'] is None
    assert issues


def test_confirmation_cannot_bypass_missing_or_invalid_dates():
    for field in ('招聘启动日期', '入职日期'):
        for value in ('', 'not-a-date'):
            result, issues = cycle({**confirmed_values(snapshot=True), field: value}, 42, '2026-07')
            assert result['factor'] is None
            assert issues


def test_original_date_confirmation_preserves_exclusion_basis_requirement():
    values={**confirmed_values(snapshot=True),'周期剔除天数':2,'负周期确认剔除天数':2}
    result,issues=cycle(values,42,'2026-07')
    assert result['actualDays']==-3 and '周期剔除依据待核' in issues
    result,issues=cycle(values,42,'2026-07',exclusion_basis={'sourceId':'existing'})
    assert not issues and result['exclusionBasis']['sourceId']=='existing'


@pytest.mark.parametrize('version', ['legacy', '2026-07'])
def test_confirmation_does_not_change_normal_periods(version):
    values = confirmed_values(snapshot=True)
    values['招聘启动日期'] = '2026-01-01'
    plain = deepcopy(values)
    for key in list(plain):
        if key.startswith('负周期确认'):
            del plain[key]
    assert cycle(values, 42, version) == cycle(plain, 42, version)


@pytest.mark.parametrize('version', ['legacy', '2026-07'])
def test_unconfirmed_negative_dates_block_recruitment_but_not_referral(version):
    row = person('2026-07-13', 招聘启动日期='2026-07-15', 周期剔除天数=0)
    row['rule']['version'] = version
    assert award(row, 'recruitment', 202608)['total'] is None
    assert award(row, 'referral', 202608)['total'] is not None


def test_confirmed_two_day_anomaly_preserves_dates_and_unblocks_recruitment_amount():
    row = person('2026-07-13', 招聘启动日期='2026-07-15', 周期剔除天数=0,
                 招聘渠道='内推', 负周期确认启动日期='2026-07-15',
                 负周期确认入职日期='2026-07-13', 负周期确认剔除天数=0,
                 负周期确认依据='用户选择按原日期核算')
    before = deepcopy(row)
    result = award(row, 'recruitment', 202608)
    assert result['total'] == 28.6
    assert result['currentAmount'] == 14.3
    assert result['issues'] == []
    assert row == before
