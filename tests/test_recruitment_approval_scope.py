from copy import deepcopy
import pytest

from bonus_platform.engine.recruitment_attention import project as attention
from bonus_platform.engine.recruitment_work_items import project
from test_recruitment_attention import state_for
from test_recruitment_awards import person


def approval_state():
    row = person('2026-06-15', 姓名='Matched Person', 招聘负责人姓名='Approved Recruiter', 招聘负责人工号='zt-approved')
    row['offerMatched'] = True
    state = state_for([row], [])
    state['sources'] = [
        {'id': 'oa1', 'name': 'OA1.pdf', 'active': True, 'attachment': True},
        {'id': 'oa2', 'name': 'OA2.pdf', 'active': True, 'attachment': True, 'mentionedAttachments': ['名单.xlsx']},
    ]
    state['todos'] = [{'id': sid, 'kind': 'attachment_review', 'title': '审批剩余范围待核',
                       'rowIds': [], 'sourceIds': [sid], 'detail': ''} for sid in ('oa1', 'oa2')]
    state['reviewEntries'] = [{'sourceId': 'oa1', 'status': '已认可', 'scopeChecked': True,
        'personScope': [
            {'name': 'Matched Person', 'rowId': row['id'], 'reason': '已唯一核实本次任职'},
            {'name': 'Missing Person', 'reason': '现有资料未找到对应人员'},
            {'name': 'Abandoned Person', 'reason': '只找到已废弃Offer，无实际入职记录'},
        ], 'recruiter': {'name': 'Approved Recruiter', 'employeeId': 'zt-approved'}}]
    return state


def test_named_scope_and_missing_attachment_are_separate_and_read_only():
    state = approval_state(); before = deepcopy(state)
    items = project(state, attention(state))
    scope = next(i for i in items if i['key'] == 'approval:oa1')
    attachment = next(i for i in items if i['key'] == 'attachment_review')
    assert scope['sourceIds'] == ['oa1'] and attachment['sourceIds'] == ['oa2']
    assert '人员匹配' in scope['title'] and '名单.xlsx' in attachment['detail']
    assert [p['status'] for p in scope['approvalPeople']] == ['已处理', '待匹配', '待匹配']
    assert '废弃' in scope['approvalPeople'][2]['reason']
    assert state == before


def test_reverted_assignment_does_not_stay_processed():
    state = approval_state()
    state['rows'][0]['values']['招聘负责人工号'] = 'zt-other'
    item = next(i for i in project(state, attention(state)) if i['key'] == 'approval:oa1')
    assert item['approvalPeople'][0]['status'] == '待更正'


def test_inactive_scope_review_is_not_used():
    state = approval_state()
    state['reviewEntries'][0]['operationId'] = 'undone'
    item = next(i for i in project(state, attention(state)) if i['key'] == 'approval:oa1')
    assert not item.get('approvalPeople')


def test_scope_is_validated_and_preserved_in_review(monkeypatch):
    from bonus_platform.engine import recruitment_reviews as reviews
    state = approval_state()
    info = {'pageCount': 1, 'mentionedAttachments': [], 'pages': [{'page': 1,
        'text': 'Matched Person Missing Person Abandoned Person Approved Recruiter zt-approved'}]}
    monkeypatch.setattr(reviews, 'document', lambda *args: info)
    evidence = {**state['reviewEntries'][0], 'pageNumbers': [1], 'note': '已核对正文和匹配结果'}
    checked = reviews.evidence_check(None, state, evidence)
    assert len(checked['personScope']) == 3
    assert checked['recruiter']['employeeId'] == 'zt-approved'
    broken = deepcopy(evidence); broken['personScope'][1]['rowId'] = state['rows'][0]['id']
    with pytest.raises(ValueError, match='不匹配'):
        reviews.evidence_check(None, state, broken)
    broken = deepcopy(evidence); broken['personScope'][1]['name'] = 'Not In Approval'
    with pytest.raises(ValueError, match='姓名'):
        reviews.evidence_check(None, state, broken)
