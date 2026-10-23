from copy import deepcopy
import json
from threading import Event, Thread
import time

import pytest

from bonus_platform.engine import recruitment_awards as awards
from bonus_platform.engine import recruitment_beisen as beisen
from bonus_platform.engine import recruitment_drafts as drafts
from bonus_platform.engine import recruitment_prepare as jobs
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_drafts import book
from test_recruitment_external_results import adopt, upload, view


MONTH = 202608


def source_store(tmp_path):
    store = DraftStore(tmp_path)
    state = store.ingest(MONTH, [('roster.xlsx', book(
        ['姓名', '工号', '入职日期', '人员状态', '人员来源'],
        [['甲', 'zt1', '2026-08-01', '正式', 'EHR入职']],
    ))], 0)
    return store, state


def test_local_reread_does_not_query_hr_or_create_another_revision(tmp_path, monkeypatch):
    store,state=source_store(tmp_path)
    def forbidden(*args,**kwargs):pytest.fail('Rereading saved files must not query HR')
    for name in ('fetch','fetch_employment','fetch_channel_details'):monkeypatch.setattr(beisen,name,forbidden)
    job=jobs.start(store,MONTH,state['revision'],local_only=True)
    assert job['localOnly'] is True
    result=settled(store)
    assert result['status']=='complete'
    assert store.read(MONTH)['revision']==state['revision']


def settled(store):
    for _ in range(500):
        result = jobs.read(store, MONTH)
        if result['status'] not in {'running', 'cancelling'}:
            assert jobs.key_for(store, MONTH) not in jobs.RUNNING
            return result
        time.sleep(.01)
    pytest.fail('Preparation did not acknowledge completion or cancellation')


def stop_without_month_lock(store, job):
    stopped = Event()
    result = []

    def request():
        result.append(jobs.cancel(store, MONTH, job['id']))
        stopped.set()

    thread = Thread(target=request)
    thread.start()
    assert stopped.wait(2), 'Stop must not wait for the worker-held monthly lock'
    thread.join()
    assert result[0]['status'] == 'cancelling'
    assert jobs.RUNNING[jobs.key_for(store, MONTH)] == job['id']
    return result[0]


def test_stop_during_refresh_discards_rebuild_and_retains_single_flight(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    state['assemblyVersion'] = -1
    store._write(store._folder(MONTH) / 'draft.json', state)
    before = (store._folder(MONTH) / 'draft.json').read_bytes()
    entered, release = Event(), Event()
    rebuild = store._rebuild

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return rebuild(*args, **kwargs)

    monkeypatch.setattr(store, '_rebuild', gated)
    monkeypatch.setattr(beisen, 'fetch', lambda *args, **kwargs: pytest.fail('Cancelled refresh must not start HR queries'))
    job = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    try:
        stop_without_month_lock(store, job)
        assert jobs.read(store, MONTH)['status'] == 'cancelling'
        assert jobs.start(store, MONTH, state['revision'])['id'] == job['id']
        assert jobs.cancel(store, MONTH, job['id'])['status'] == 'cancelling'
    finally:
        release.set()
    assert settled(store)['status'] == 'cancelled'
    assert (store._folder(MONTH) / 'draft.json').read_bytes() == before
    assert not (store._folder(MONTH) / 'revisions' / f"{state['revision'] + 1}.json").exists()
    assert jobs.read(store, MONTH)['status'] == 'cancelled'


def test_stop_after_inflight_hr_response_stops_pagination_and_does_not_save(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    before = (store._folder(MONTH) / 'draft.json').read_bytes()
    entered, release = Event(), Event()
    calls = []

    class Client:
        def post(self, path, body):
            calls.append(path)
            if path == beisen.IDS:
                return {'data': [{'jobNumber': 'zt1', 'userId': 'user1', 'code': 200}]}
            if path == beisen.HISTORY:
                return {'data': [{'jobNumber': 'zt1', 'userID': 'user1', 'approvalStatus': 4, 'lUOffer': 'offer1'}]}
            assert path == beisen.OFFERS
            entered.set()
            assert release.wait(5)
            return {'data': [{'objectId': 'offer1'}], 'scrollId': 'next-page'}

    monkeypatch.setattr(beisen, 'Client', Client)
    job = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    try:
        stop_without_month_lock(store, job)
        assert jobs.read(store, MONTH)['status'] == 'cancelling'
    finally:
        release.set()
    assert settled(store)['status'] == 'cancelled'
    assert calls == [beisen.IDS, beisen.HISTORY, beisen.OFFERS]
    assert (store._folder(MONTH) / 'draft.json').read_bytes() == before
    assert len(store.read(MONTH)['sources']) == 1


def test_stop_during_row_calculation_does_not_commit_partial_revision(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    state['calculation']['engineVersion'] = -1
    store._write(store._folder(MONTH) / 'draft.json', state)
    before = (store._folder(MONTH) / 'draft.json').read_bytes()
    entered, release = Event(), Event()
    calculate = awards.calculate_row

    def gated(*args):
        result = calculate(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(awards, 'calculate_row', gated)
    job = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    try:
        stop_without_month_lock(store, job)
    finally:
        release.set()
    assert settled(store)['status'] == 'cancelled'
    assert (store._folder(MONTH) / 'draft.json').read_bytes() == before
    assert not (store._folder(MONTH) / 'revisions' / f"{state['revision'] + 1}.json").exists()


def test_stop_during_commit_finishes_revision_pair_before_acknowledging(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    state['calculation']['engineVersion'] = -1
    store._write(store._folder(MONTH) / 'draft.json', state)
    entered, release = Event(), Event()
    write = store._write_json

    def gated(path, content):
        write(path, content)
        value = json.loads(content)
        if path.parent.name == 'revisions' and value['revision'] == state['revision'] + 1:
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(store, '_write_json', gated)
    job = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    try:
        stop_without_month_lock(store, job)
        assert jobs.read(store, MONTH)['status'] == 'cancelling'
    finally:
        release.set()
    assert settled(store)['status'] == 'cancelled'
    current = (store._folder(MONTH) / 'draft.json').read_bytes()
    revision = (store._folder(MONTH) / 'revisions' / f"{state['revision'] + 1}.json").read_bytes()
    assert current == revision
    assert json.loads(current)['revision'] == state['revision'] + 1


def test_cancelled_job_can_retry_and_old_stop_cannot_cancel_new_job(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    entered, release = Event(), Event()

    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {}

    monkeypatch.setattr(beisen, 'fetch', fetch)
    first = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    jobs.cancel(store, MONTH, first['id'])
    release.set()
    assert settled(store)['status'] == 'cancelled'
    entered.clear()
    release.clear()
    second = jobs.start(store, MONTH, state['revision'])
    assert second['id'] != first['id']
    assert entered.wait(3)
    try:
        with pytest.raises(ValueError):
            jobs.cancel(store, MONTH, first['id'])
        assert jobs.read(store, MONTH)['status'] == 'running'
        assert jobs.RUNNING[jobs.key_for(store, MONTH)] == second['id']
        jobs.cancel(store, MONTH, second['id'])
    finally:
        release.set()
    assert settled(store)['status'] == 'cancelled'


def test_query_failure_after_stop_is_cancelled_instead_of_failed(tmp_path, monkeypatch):
    store, state = source_store(tmp_path)
    entered, release = Event(), Event()

    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise ValueError('网络连接未完成')

    monkeypatch.setattr(beisen, 'fetch', fetch)
    job = jobs.start(store, MONTH, state['revision'])
    assert entered.wait(3)
    jobs.cancel(store, MONTH, job['id'])
    release.set()
    assert settled(store)['status'] == 'cancelled'


@pytest.mark.parametrize('terminal', ['complete', 'failed'])
def test_terminal_job_is_not_changed_by_stop(tmp_path, monkeypatch, terminal):
    store, state = source_store(tmp_path)

    def fetch(*args, **kwargs):
        if terminal == 'failed':
            raise ValueError('接口未完成')
        return {}

    monkeypatch.setattr(beisen, 'fetch', fetch)
    monkeypatch.setattr(store, 'save_beisen_snapshot', lambda *args: state)
    job = jobs.start(store, MONTH, state['revision'])
    assert settled(store)['status'] == terminal
    path = store._folder(MONTH) / 'prepare.json'
    before = path.read_bytes()
    assert jobs.cancel(store, MONTH, job['id'])['status'] == terminal
    assert path.read_bytes() == before


def test_unchanged_external_results_refresh_reuses_saved_calculation(tmp_path, monkeypatch):
    store = DraftStore(tmp_path)
    state = adopt(store, upload(store, [['体系外甲', '招聘负责人奖金', '体系外乙', 123.45, 'CNY']]))
    financial = deepcopy(view(state))
    before = (store._folder(MONTH) / 'draft.json').read_bytes()
    monkeypatch.setattr(store, '_rebuild', lambda *args, **kwargs: pytest.fail('Unchanged external results must not rebuild'))
    refreshed = store.refresh(MONTH, state['revision'])
    assert refreshed['revision'] == state['revision']
    assert view(refreshed) == financial
    assert (store._folder(MONTH) / 'draft.json').read_bytes() == before


def test_external_results_engine_change_still_recalculates(tmp_path):
    store = DraftStore(tmp_path)
    state = adopt(store, upload(store, [['体系外甲', '招聘负责人奖金', '体系外乙', 123.45, 'CNY']]))
    financial = deepcopy(view(state))
    state['calculation']['engineVersion'] = -1
    store._write(store._folder(MONTH) / 'draft.json', state)
    refreshed = store.refresh(MONTH, state['revision'])
    assert refreshed['revision'] == state['revision'] + 1
    assert view(refreshed)['totals'] == financial['totals']
    assert view(refreshed)['nodes'] == financial['nodes']


def test_external_results_source_replacement_is_persisted_once(tmp_path):
    store, state = source_store(tmp_path)
    state = adopt(store, upload(store, [['体系外甲', '招聘负责人奖金', '体系外乙', 123.45, 'CNY']], state['revision']))
    source = next(s for s in state['sources'] if s['name'] == 'roster.xlsx')
    original = store._folder(MONTH) / 'sources' / source['storedName']
    original.write_bytes(book(['姓名', '工号', '入职日期', '人员状态', '人员来源', '职级'],
                              [['甲', 'zt1', '2026-08-01', '正式', 'EHR入职', 'P3']]))
    refreshed = store.refresh(MONTH, state['revision'])
    assert refreshed['revision'] == state['revision'] + 1
    assert next(r for r in refreshed['rows'] if r['values'].get('工号') == 'zt1')['values']['职级'] == 'P3'
    persisted = json.loads((store._folder(MONTH) / 'draft.json').read_text())
    assert persisted['revision'] == refreshed['revision']
    assert view(persisted)['totals'] == view(refreshed)['totals']
    assert next(r for r in persisted['rows'] if r['values'].get('工号') == 'zt1')['values']['职级'] == 'P3'
    assert store.refresh(MONTH, refreshed['revision'])['revision'] == refreshed['revision']


def test_external_proof_deactivation_and_restoration_refresh_cached_amounts(tmp_path):
    store = DraftStore(tmp_path)
    state = adopt(store, upload(store, [['体系外甲', '招聘负责人奖金', '体系外乙', 123.45, 'CNY']]))
    source = state['sources'][0]
    source['active'] = False
    store._write(store._folder(MONTH) / 'draft.json', state)
    invalid = store.refresh(MONTH, state['revision'])
    assert invalid['revision'] == state['revision'] + 1
    assert not any(n.get('amount') for r in invalid['rows'] for a in r['calculation'].values() if isinstance(a, dict) for n in a.get('nodes', []))
    source = invalid['sources'][0]
    source['active'] = True
    store._write(store._folder(MONTH) / 'draft.json', invalid)
    restored = store.refresh(MONTH, invalid['revision'])
    assert restored['revision'] == invalid['revision'] + 1
    assert view(restored)['totals'][0]['confirmed'] == 123.45
    assert store.refresh(MONTH, restored['revision'])['revision'] == restored['revision']
