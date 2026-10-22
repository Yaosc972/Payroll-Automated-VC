"""Repeated detail reads reuse immutable input work without hiding changed files."""
from pathlib import Path
import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from bonus_platform.engine import recruitment_attention as attention
from bonus_platform.engine import recruitment_work_items as work
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_drafts import book
from test_recruitment_reference_facts import fixture, adopt


def test_repeated_work_item_reads_do_not_reload_parsed_records(tmp_path, monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    store, state, _ = fixture(tmp_path)
    state = adopt(store, state)
    item = next(i for i in work.project(state, attention.project(state)) if i['mode'] == 'recipient')
    monkeypatch.setattr(api, 'store', store)
    reads = {}
    original = Path.read_text

    def tracked(path, *args, **kwargs):
        if path.parent.name == 'parsed':
            reads[str(path)] = reads.get(str(path), 0) + 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', tracked)
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    url = f"/api/recruitment/drafts/202607/work-items/{item['id']}?revision={state['revision']}"
    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert all(count <= 1 for count in reads.values()), reads
    assert store.read(202607)['revision'] == state['revision']


def test_work_item_reuses_its_attention_projection(tmp_path, monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    store, state, _ = fixture(tmp_path)
    state = adopt(store, state)
    item = next(i for i in work.project(state, attention.project(state)) if i['mode'] == 'recipient')
    monkeypatch.setattr(api, 'store', store)
    calls = []
    original = attention.project

    def tracked(state):
        calls.append(state['revision'])
        return original(state)

    monkeypatch.setattr(api, 'attention_project', tracked)
    monkeypatch.setattr(attention, 'project', tracked)
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get(
        f"/api/recruitment/drafts/202607/work-items/{item['id']}?revision={state['revision']}")
    assert response.status_code == 200
    assert len(calls) == 1


def test_recipient_detail_does_not_reinterpret_unrelated_approvals(tmp_path, monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    from bonus_platform.engine import recruitment_approval_intake as approvals
    store, state, _ = fixture(tmp_path)
    state = adopt(store, state)
    item = next(i for i in work.project(state, attention.project(state)) if i['mode'] == 'recipient')
    monkeypatch.setattr(api, 'store', store)

    def unrelated_approvals(*args):
        raise AssertionError('A recipient detail should not reinterpret all approval documents')

    monkeypatch.setattr(approvals, 'project', unrelated_approvals)
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get(
        f"/api/recruitment/drafts/202607/work-items/{item['id']}?revision={state['revision']}")
    assert response.status_code == 200
    assert response.json()['mode'] == 'recipient'


def test_approval_detail_still_uses_recognized_scope(tmp_path, monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    from bonus_platform.engine import recruitment_approval_intake as approvals
    from test_recruitment_approval_intake import setup
    store, state = setup(tmp_path, monkeypatch, {'周期': '候选人：候选甲。申请剔除10天签证办理时间。'})
    projected, _ = approvals.project(store, state)
    item = next(i for i in work.project(projected, attention.project(projected))
                if i['key'] == 'approval:ready')
    assert not any(i['id'] == item['id'] for i in work.project(state, attention.project(state)))
    monkeypatch.setattr(api, 'store', store)
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get(
        f"/api/recruitment/drafts/202607/work-items/{item['id']}?revision={state['revision']}")
    assert response.status_code == 200
    assert response.json()['key'] == 'approval:ready'
    assert response.json()['sourceIds'] == item['sourceIds']


@pytest.mark.parametrize('change', ['version', 'same_size', 'corrupt', 'missing'])
def test_warm_metadata_does_not_hide_replaced_or_missing_parsed_file(tmp_path, monkeypatch, change):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('补充.xlsx', book(
        ['体系外人员编号', '姓名', '工号', '入职日期'], [['a', '甲', 'zt1', '2026-07-01']]))], 0)
    source = state['sources'][0]
    path = store._folder(202607) / 'parsed' / (source['id'] + '.json')
    store.read(202607)
    stamp = path.stat()
    if change in {'version', 'same_size'}:
        data = json.loads(path.read_text())
        data['parserVersion'] -= 1
        if change == 'same_size':
            content = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            assert len(content.encode()) == stamp.st_size
            path.write_text(content)
            assert path.stat().st_ino == stamp.st_ino
        else:
            store._write(path, data)
    elif change == 'corrupt':
        path.write_text('{')
    else:
        path.unlink()
    if path.exists():
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    parses = []
    original = store._parse_source

    def tracked(folder, source):
        parses.append(source['id'])
        return original(folder, source)

    monkeypatch.setattr(store, '_parse_source', tracked)
    restored = store.read(202607)
    assert parses == [source['id']]
    assert restored['rows'][0]['values']['姓名'] == '甲'
    assert restored['revision'] == state['revision']
