from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_awards import award, ensure_calculated
from bonus_platform.engine.recruitment_attention import project as attention
from bonus_platform.engine.recruitment_work_items import project as work_items
from test_recruitment_awards import person
from test_recruitment_attention import state_for
from test_recruitment_drafts import book


@pytest.mark.parametrize('job',['操作类','操作工','一线操作类','操作管理类','操作支持类'])
def test_job_classification_alone_does_not_require_scope_approval(tmp_path,job):
    values=person(职类=job)['values']
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('原始资料.xlsx',book(list(values),[list(values.values())],'导入_月度数据'))],0)
    row=state['rows'][0]
    assert row['scopeStatus']=='已纳入底稿'
    assert row['values']['职类']==job
    assert '核算范围' not in row['values']
    assert row['calculation']['recruitment']['total']==55
    assert row['calculation']['referral']['total']==400
    assert all('人员核算范围待核' not in row['calculation'][kind]['issues'] for kind in ('recruitment','referral'))
    assert not any(item['key']=='operator-scope' for item in work_items(state,attention(state)))


def test_saved_operator_diagnostic_is_recomputed_without_overwriting_facts():
    row=person(职类='操作类',招聘渠道='不明确的渠道')
    row['scopeStatus']='操作类范围待核'
    values=deepcopy(row['values'])
    state=state_for([row],[])
    row['scopeStatus']='操作类范围待核'  # Simulate an old persisted diagnostic.
    state['calculation']['engineVersion']='4.4'
    ensure_calculated(state)
    assert row['values']==values
    assert row['scopeStatus']=='已纳入底稿'
    assert '人员核算范围待核' not in row['calculation']['recruitment']['issues']
    assert '招聘渠道待核' in row['calculation']['recruitment']['issues']
    assert row['calculation']['recruitment']['total'] is None
    assert attention(state)['current']  # Real uncertainty is not hidden.


@pytest.mark.parametrize('scope,expected',[('不纳入核算',0),('纳入核算',400)])
def test_saved_manual_scope_decision_survives_diagnostic_upgrade(scope,expected):
    row=person(职类='操作类',核算范围=scope)
    row['scopeStatus']='操作类范围待核'
    state=state_for([row],[])
    assert row['values']['核算范围']==scope
    assert row['calculation']['referral']['total']==expected


def test_operator_uses_applicable_legacy_special_and_new_standards_separately():
    old=person('2026-06-01',职类='操作工',职级='P1-2',ABC类别='不占编',旧特殊规则依据='德国已确认制度')
    old['rule']['specialScope']='FBU德国'
    assert award(old,'referral',202607)['total']==100
    new=person(职类='操作工',职级='P1-2')
    assert award(new,'referral',202607)['total']==400


def test_unresolved_employment_scope_is_not_cleared_with_operator_diagnostic():
    row=person(职类='操作类',人员来源='人员迁移')
    row['scopeStatus']='范围待核';row['rule']['version']='unresolved'
    state=state_for([row],[])
    assert row['scopeStatus']=='范围待核'
    assert '人员核算范围待核' in row['calculation']['recruitment']['issues']
    assert row['calculation']['recruitment']['total'] is None
