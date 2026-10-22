"""Reproduce audit findings with synthetic XLSX files in temporary directories."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from bonus_platform import recruitment_draft_api as api
from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_trials import ACTIVITY, ScopedDraftStore
from bonus_platform.engine.recruitment_monthly import recipient_summaries, export
from test_recruitment_awards import person
from test_recruitment_drafts import book


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def fixture(**values):
    original_store = api.store
    with TemporaryDirectory(prefix='recruitment-calculation-audit-') as temporary:
        store = ScopedDraftStore(Path(temporary) / 'drafts')
        api.store = store
        app = FastAPI()
        for router in (api.router, api.activities_router, api.activity_drafts_router):
            app.include_router(router)
        client = TestClient(app)
        activity = checked(client.post('/api/recruitment/activities', json={'month': 202607}))
        base = f"/api/recruitment/activities/{activity['id']}/api/recruitment/drafts/202607"
        adopted = person('2026-07-01', 姓名='合成核验人员', 工号='ext1', 体系外人员编号='outside1',
                         推荐人工号='', 推荐人姓名='')['values']
        adopted.update(values)
        state = checked(client.post(base + '/sources', data={'revision': 0, 'periodConfirmed': 'true'}, files=[
            ('files', ('原始资料.xlsx', book(list(adopted), [list(adopted.values())], '导入_月度数据'))),
            ('files', ('花名册.xlsx', book(['姓名', '工号', '入职日期', '人员状态', '人员来源'],
                                       [['合成核验人员', 'ext1', '2026-07-01', '正式', 'OEHR入职']]))),
        ]))
        state = checked(client.post(base + '/opening-empty', json={'revision': state['revision'], 'confirmed': True}))
        try:
            yield client, store, activity, base, state, adopted
        finally:
            api.store = original_store


def conflict(client, base, state, values):
    return checked(client.post(base + '/sources',
        data={'revision': state['revision'], 'periodConfirmed': 'true'},
        files=[('files', ('第二份资料.xlsx', book(list(values), [list(values.values())], '导入_月度数据')))]))


def raw(store, activity):
    token = ACTIVITY.set(activity['id'])
    try:
        return store.read(activity['month'])
    finally:
        ACTIVITY.reset(token)


def confirm(client, base, state):
    return client.post(base + '/confirm-month', json={'revision': state['revision'], 'coverageConfirmed': True}).status_code


def country_conflict():
    with fixture() as (client, store, activity, base, state, values):
        state = conflict(client, base, state, {**values, '二级组织': '美国', '工作地': '美国'})
        row = raw(store, activity)['rows'][0]
        status = confirm(client, base, state)
        assert set(row['unresolvedFields']) == {'二级组织', '工作地'}
        assert not state['monthly']['cases'] and status == 200
        return {'unresolvedFields': row['unresolvedFields'], 'cases': state['monthly']['cases'],
                'totals': state['monthly']['totals'], 'confirmHttp': status}


def zero_qualification_conflict():
    with fixture(推荐人工号='zt-ref', 推荐人姓名='推荐人', 推荐人职级='P4-1') as (client, store, activity, base, state, values):
        state = conflict(client, base, state, {**values, '推荐人职级': 'P2-1'})
        row = raw(store, activity)['rows'][0]
        status = confirm(client, base, state)
        alternative = award({**row, 'values': {**row['values'], '推荐人职级': 'P2-1'}, 'unresolvedFields': []}, 'referral', 202607)
        assert row['unresolvedFields'] == ['推荐人职级'] and row['calculation']['referral']['total'] == 0
        assert not state['monthly']['cases'] and status == 200 and alternative['currentAmount'] == 200
        return {'unresolvedFields': row['unresolvedFields'], 'referralTotal': 0,
                'alternativeCurrentAmount': alternative['currentAmount'], 'cases': state['monthly']['cases'], 'confirmHttp': status}


def carry_arrangements():
    with fixture() as (client, store, activity, base, state, values):
        assert confirm(client, base, state) == 200
        previous = state['monthly']['nodes'][0]
        child = checked(client.post('/api/recruitment/activities', json={'month': 202608,
            'opening': {'activityId': activity['id'], 'revision': state['revision']}}))
        child_base = f"/api/recruitment/activities/{child['id']}/api/recruitment/drafts/202608"
        carried = checked(client.get(child_base))
        old = next(n for n in carried['monthly']['nodes'] if n['id'] == previous['id'])
        assert previous['month'] == 202607 and old['month'] is None and old['status'] == '往期未安排'
        changed = checked(client.post(child_base + '/changes', json={'revision': carried['revision'], 'edits': [
            {'rowId': carried['rows'][0]['id'], 'field': '招聘启动日期', 'value': '2026-06-27'}]}))
        future = next(n for n in changed['monthly']['nodes'] if n['label'] == '入职满三个月')
        assert future['amount'] == 35.75
        return {'confirmedPriorAmount': previous['amount'], 'priorMonthAfterCarry': old['month'],
                'priorStatusAfterCarry': old['status'], 'validationProblems': carried['ruleValidation']['problems'],
                'repricedTotal': changed['rows'][0]['calculation']['recruitment']['total'],
                'futureAmountAfterReprice': future['amount'], 'expectedRemainderAfterPreservingPriorArrangement': 44}


def mixed_currency_export():
    def node(kind, currency, amount):
        return {'rowId': 'synthetic', 'kind': kind, 'scope': 'current', 'role': '招聘负责人' if kind == 'recruitment' else '推荐人',
                'recipientId': 'zt-payee', 'recipientName': '合成领取人', 'currency': currency,
                'label': '入职满一个月', 'amount': amount, 'review': False, 'reasons': []}
    nodes = [node('recruitment', '欧元', 5), node('recruitment', '美元', 8),
             node('referral', '人民币', 300), node('referral', '欧元', 200)]
    state = {'month': 202607, 'rows': []}
    summary = recipient_summaries(state, nodes)
    assert summary['recruitment']['rows'][0]['confirmed'] == 13
    assert summary['referral']['rows'][0]['confirmed'] == 500
    monthly = {'worksheet': {'columns': [{'key': 'name', 'label': '姓名', 'group': '人员资料', 'type': 'text'}], 'rows': []},
               'nodes': nodes, 'recipientSummaries': summary}
    workbook = load_workbook(BytesIO(export(state, monthly)), data_only=True)
    cells = list(workbook.worksheets[1].values)
    assert any(13 in row for row in cells[2:])
    return {'recruitment': summary['recruitment']['rows'], 'referral': summary['referral']['rows'],
            'referralTotals': summary['referral']['totals'], 'exportContainsMixedTotal13': True}


def invalid_exception():
    with fixture(招聘负责人最后工作日='2026-01-01') as (client, store, activity, base, state, values):
        node = state['monthly']['nodes'][0]
        preview = checked(client.post(base + '/special/preview', json={
            'revision': state['revision'], 'basisType': 'manual', 'type': 'exception',
            'rowId': node['rowId'], 'nodeId': node['id'], 'kind': 'recruitment', 'month': 202607,
            'conditions': ['recipient_not_employed']}))
        applied = checked(client.post(base + '/special/previews/' + preview['id'] + '/apply', json={'revision': state['revision']}))
        changed = checked(client.post(base + '/changes', json={'revision': applied['revision'], 'edits': [
            {'rowId': node['rowId'], 'field': 'ABC类别', 'value': 'B'}]}))
        invalid = next(n for n in changed['monthly']['nodes'] if n['id'] == node['id'])
        status = confirm(client, base, changed)
        assert invalid['issues'] and invalid['scope'] == 'held' and not changed['monthly']['cases'] and status == 200
        return {'previousCurrentAmount': applied['rows'][0]['calculation']['recruitment']['currentAmount'],
                'afterCurrentAmount': changed['rows'][0]['calculation']['recruitment']['currentAmount'],
                'nodeIssues': invalid['issues'], 'cases': changed['monthly']['cases'], 'confirmHttp': status}


if __name__ == '__main__':
    result = {'CALC-01': country_conflict(), 'CALC-02': zero_qualification_conflict(),
              'CALC-03': carry_arrangements(), 'CALC-04': mixed_currency_export(),
              'CALC-05': invalid_exception()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
