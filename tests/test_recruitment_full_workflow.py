from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from test_recruitment_activities import activities, base, create
from test_recruitment_awards import person
from test_recruitment_drafts import book


def workflow_files():
    values = [person('2026-07-01', 姓名=name, 工号=number, 体系外人员编号=number,
        工作地=country, 二级组织=country, 招聘负责人工号='ov900', 推荐人工号='', 推荐人姓名='')['values']
        for name, number, country in [('验收甲', 'ov101', '德国'), ('验收乙', 'ov102', '美国')]]
    headers = list(values[0])
    source = book(headers, [[v.get(k, '') for k in headers] for v in values], '导入_月度数据')
    roster = book(['姓名', '工号', '入职日期', '人员状态', '人员来源'],
        [[v['姓名'], v['工号'], v['入职日期'], '正式', 'OEHR入职'] for v in values])
    pdf = (Path(__file__).parent/'fixtures/recruitment-workflow-approval.pdf').read_bytes()
    return [('原始资料.xlsx', source), ('花名册.xlsx', roster), ('周期审批.pdf', pdf)]


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_approval_undo_export_confirm_and_carry(activities):
    client, store = activities
    activity = create(client, '完整流程验收')
    endpoint = base(activity)
    state = ok(client.post(endpoint+'/sources', data={'revision': 0, 'periodConfirmed': 'true'},
        files=[('files', (name, content)) for name, content in workflow_files()]))
    state = ok(client.post(endpoint+'/opening-empty', json={'revision': state['revision'], 'confirmed': True}))
    items = state['approvalAdjustments']['items']
    assert len(items) == 2
    assert {i['person']['employeeId'] for i in items} == {'ov101', 'ov102'}
    assert all(i['status'] == 'ready' for i in items)
    assert all(next(f['value'] for f in i['fields'] if f['field'] == '周期剔除天数') == 5 for i in items)
    preview = ok(client.post(endpoint+'/approval-adjustments/preview', json={
        'revision': state['revision'], 'itemIds': [i['id'] for i in items]}))
    saved = ok(client.post(endpoint+'/previews/'+preview['id']+'/apply', json={'revision': state['revision']}))
    retry = ok(client.post(endpoint+'/previews/'+preview['id']+'/apply', json={'revision': state['revision']}))
    assert retry['revision'] == saved['revision']
    assert all(r['values']['周期剔除天数'] == 5 for r in saved['rows'])
    undone = ok(client.post(endpoint+'/history', json={'revision': saved['revision'], 'action': 'undo'}))
    assert all(not r['values'].get('周期剔除天数') for r in undone['rows'])
    saved = ok(client.post(endpoint+'/history', json={'revision': undone['revision'], 'action': 'redo'}))
    assert all(r['values']['周期剔除天数'] == 5 for r in saved['rows'])
    assert not saved['monthly']['cases']
    review = ok(client.get(endpoint+'/review-center', params={'revision': saved['revision']}))
    assert not [w for w in review['workItems'] if w['current']]
    summary = saved['monthly']['recipientSummaries']['recruitment']
    assert {r['currency'] for r in summary['rows']} == {'欧元', '美元'}
    assert {t['currency'] for t in summary['totals']} == {'欧元', '美元'}
    response = client.get(endpoint+'/monthly/export', params={'revision': saved['revision']})
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content), data_only=True)
    exported = list(workbook.worksheets[1].values)
    assert any('欧元' in row for row in exported) and any('美元' in row for row in exported)
    assert not any('美元/欧元' in row for row in exported)
    prior = {n['id']: n for n in saved['monthly']['nodes'] if n['scope'] == 'current'}
    assert prior
    ok(client.post(endpoint+'/confirm-month', json={'revision': saved['revision'], 'coverageConfirmed': True}))
    child = create(client, '承接验收', 202608, opening={'activityId': activity['id'], 'revision': saved['revision']})
    carried = ok(client.get(base(child)))
    for node in carried['monthly']['nodes']:
        if node['id'] in prior:
            original = prior[node['id']]
            assert (node['month'], node['amount'], node['currency'], node['recipientId']) == (
                202607, original['amount'], original['currency'], original['recipientId'])
            assert node['scope'] == 'history'
    assert set(prior) <= {n['id'] for n in carried['monthly']['nodes']}
    assert not carried['paymentReady']
    assert ok(client.get(endpoint))['revision'] == saved['revision']
