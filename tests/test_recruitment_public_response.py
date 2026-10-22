from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform import recruitment_draft_api as api
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_drafts import book


def setup(tmp_path, monkeypatch):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('人员.xlsx', book(
        ['姓名', '工号', '入职日期', '人员状态', '人员来源'],
        [['甲', 'zt1', '2026-07-01', '正式', 'EHR入职']]))], 0)
    monkeypatch.setattr(api, 'store', store)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), store, state


def test_read_preserves_complete_json_object_without_generic_reencoding(tmp_path, monkeypatch):
    client, store, state = setup(tmp_path, monkeypatch)
    receipt = {'revision': state['revision'], 'confirmedAt': '2026-10-20T12:00:00'}
    store._write(store._folder(202607) / 'accepted-status.json', receipt)
    expected = api.public(store.read(202607))
    assert isinstance(expected, dict)
    expected.update(previousAvailable=False, previousMonth=202606, previousAccepted=False, confirmation=receipt)
    with patch('fastapi.routing.jsonable_encoder', side_effect=AssertionError('native public projection must be encoded once')):
        response = client.get('/api/recruitment/drafts/202607')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/json'
    assert response.json() == expected


def test_mutation_preserves_complete_object_and_stale_revision_error(tmp_path, monkeypatch):
    client, store, state = setup(tmp_path, monkeypatch)
    row_id = state['rows'][0]['id']
    with patch('fastapi.routing.jsonable_encoder', side_effect=AssertionError('native public projection must be encoded once')):
        response = client.post('/api/recruitment/drafts/202607/changes', json={
            'revision': state['revision'], 'edits': [{'rowId': row_id, 'field': '人工备注', 'value': '已核对中文内容'}]})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/json'
    expected = api.public(store.read(202607))
    assert response.json() == expected
    assert expected['rows'][0]['values']['人工备注'] == '已核对中文内容'
    assert expected['revision'] == state['revision'] + 1
    stale = client.post('/api/recruitment/drafts/202607/changes', json={'revision': state['revision'], 'edits': []})
    assert stale.status_code == 409
    assert 'detail' in stale.json()
