"""Authenticated users keep separate activities/configuration, with shared read access."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import importlib

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

api = importlib.import_module('bonus_platform.app')
from bonus_platform.engine.domestic_labor import runs, night_shift_config as config


@pytest.fixture
def clients(monkeypatch, tmp_path):
    monkeypatch.setattr(runs, 'DOMESTIC_LABOR_RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(api, 'DOMESTIC_LABOR_RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(config, 'NIGHT_SHIFT_CONFIG_DIR', tmp_path / 'config')
    monkeypatch.setattr(runs, 'domestic_labor_persistent_storage_enabled', lambda: False)
    monkeypatch.setattr(config, 'domestic_labor_persistent_storage_enabled', lambda: False)
    monkeypatch.setattr(api, '_domestic_labor_access_response', lambda request: None)
    def current(request):
        name = request.cookies.get('test_identity')
        return {'user': {'id': name, 'name': name, 'status': 'active'}} if name else None
    monkeypatch.setattr(api, '_labor_current_user_from_request', current)
    alice, bob = TestClient(api.app), TestClient(api.app)
    alice.cookies.set('test_identity', 'Alice')
    bob.cookies.set('test_identity', 'Bob')
    return alice, bob


def create(client, name='月度核算'):
    response = client.post('/api/domestic-labor/activities', json={'month': '2026-06', 'subject': 'quanqinjiang', 'name': name, 'ownerId': 'forged'})
    assert response.status_code == 200, response.text
    return response.json()


def workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = '全勤奖'
    ws.append(['工号','姓名','考勤月份','入职日期','最后工作日','旷工天数','正班迟到次数','迟到6分钟内(次)','迟到6-20分钟内(次)','迟到20-30分钟内(次)','早退次数','签卡次数','工伤假天数','事假时数','病假时数','入离职缺勤时数','迟到早退30分钟内扣款'])
    ws.append(['QA001','测试员工','202606','2023-01-01',None,0,0,0,0,0,0,0,0,0,0,0,0])
    data = BytesIO(); wb.save(data)
    return data.getvalue()


def test_two_users_calculate_and_read_each_others_results(clients):
    alice, bob = clients
    with ThreadPoolExecutor(max_workers=2) as executor:
        activities = list(executor.map(create, [alice, bob]))
    assert activities[0]['id'] != activities[1]['id']
    def calculate(pair):
        client, activity = pair
        result = client.post('/api/domestic-labor/runs', data={'engines': 'quanqinjiang', 'attendance_month': '202606', 'activity_id': activity['id']}, files={'file': ('attendance.xlsx', workbook())})
        assert result.status_code == 200, result.text
        return result.json()['run_id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(calculate, zip([alice, bob], activities)))
    assert ids[0] != ids[1]
    for reader in (alice, bob):
        rows = reader.get('/api/domestic-labor/activities').json()['activities']
        assert len(rows) == 2
        assert sum(row['isMine'] for row in rows) == 1
        assert all(row['status'] == '已核算' for row in rows)
        assert all(row['employeeCount'] == 1 for row in rows)
        for run_id in ids:
            assert reader.get(f'/api/domestic-labor/runs/{run_id}/results').status_code == 200
            export = reader.get(f'/api/domestic-labor/runs/{run_id}/export')
            assert export.status_code == 200, export.text
            assert reader.get(f'/api/domestic-labor/runs/{run_id}/download/{export.json()["file_name"]}').status_code == 200
    assert runs.load_payroll_metadata(runs.get_payroll_run_dir(ids[0]))['ownerId'] == 'Alice'
    assert bob.delete(f'/api/domestic-labor/runs/{ids[0]}').status_code == 403
    assert alice.patch(f'/api/domestic-labor/activities/{activities[1]["id"]}', json={'name':'改名'}).status_code == 403
    assert TestClient(api.app).get('/api/domestic-labor/activities').status_code == 401


def test_owner_fields_and_summary_cannot_be_forged(clients):
    alice, bob = clients
    activity = create(alice)
    assert activity['ownerId'] == 'Alice'
    result = alice.patch(f'/api/domestic-labor/activities/{activity["id"]}', json={'ownerId':'Bob','runId':'other','payableTotal':999999,'status':'已核算','name':'更新名称'})
    assert result.status_code == 200
    saved = result.json()
    assert saved['ownerId'] == 'Alice' and saved['runId'] == '' and saved['status'] == '草稿'
    assert saved['name'] == '更新名称'
    wrong = bob.post('/api/domestic-labor/runs', data={'engines':'quanqinjiang','attendance_month':'202606','activity_id':activity['id']}, files={'file':('x.xlsx',workbook())})
    assert wrong.status_code == 403


def test_user_configuration_isolation_concurrent_requests(clients):
    alice, bob = clients
    def save(pair):
        client, employee = pair
        response = client.put('/api/domestic-labor/night-shift/config/202606', json={'jinjiang_list_confirmed':True,'jinjiang_exclusions':[{'employee_id':employee,'reason':'轻松岗位','start_date':'2026-06-01'}]})
        assert response.status_code == 200, response.text
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(save, [(alice,'A001'),(bob,'B001')]))
    for client, employee in [(alice,'A001'),(bob,'B001')]:
        value = client.get('/api/domestic-labor/night-shift/config/202606').json()
        assert [r['employee_id'] for r in value['jinjiang_exclusions']] == [employee]
        assert value['revision'] == 1
        assert len(client.get('/api/domestic-labor/night-shift/config/202606/history').json()['revisions']) == 1


def test_legacy_runs_stay_unassigned_and_configuration_hidden(clients):
    alice, _ = clients
    legacy = runs.create_payroll_run({'engines':['canbu'],'attendanceMonth':'202606','status':'已完成','summary':{'total_employees':2,'total_canbu':100}})
    runs.create_payroll_run({'kind':'configuration','config':{'secret':'not-list-data'}})
    rows = alice.get('/api/domestic-labor/activities').json()['activities']
    assert len(rows) == 1 and rows[0]['id'] == legacy['id']
    assert rows[0]['legacy'] and not rows[0]['isMine']
    assert len(alice.get('/api/domestic-labor/runs').json()['runs']) == 1


def test_direct_upload_plan_uses_session_owner_and_rejects_other_submit(clients, monkeypatch):
    alice, bob = clients
    activity = create(alice)
    monkeypatch.setattr(api, 'domestic_labor_persistent_storage_enabled', lambda: True)
    monkeypatch.setattr(api, 'create_domestic_labor_signed_upload', lambda run_id, filename: {'signedUrl':'https://example.invalid/upload'})
    payload = {'activityId':activity['id'],'files':[{'fileName':'input.xlsx','fileSize':4,'contentType':'application/octet-stream'}],'ownerId':'Bob'}
    assert bob.post('/api/domestic-labor/runs/direct-upload-plan', json=payload).status_code == 403
    response = alice.post('/api/domestic-labor/runs/direct-upload-plan', json=payload)
    assert response.status_code == 200, response.text
    run_id = response.json()['runId']
    assert runs.load_payroll_metadata(runs.get_payroll_run_dir(run_id))['ownerId'] == 'Alice'
    assert bob.post(f'/api/domestic-labor/runs/{run_id}/direct-upload-complete', json={}).status_code == 403


def test_configuration_survives_cold_worker_without_cross_user_leak(clients, monkeypatch, tmp_path):
    alice, bob = clients
    remote = {}
    monkeypatch.setattr(config, 'domestic_labor_persistent_storage_enabled', lambda: True)
    monkeypatch.setattr(config, 'load_domestic_labor_metadata_from_persistent', lambda key: remote.get(key))
    monkeypatch.setattr(config, 'save_domestic_labor_metadata_to_persistent', lambda key, data, compact: remote.update({key:data}))
    response = alice.put('/api/domestic-labor/night-shift/config/202606', json={'jinjiang_list_confirmed':True,'jinjiang_exclusions':[]})
    assert response.status_code == 200
    monkeypatch.setattr(config, 'NIGHT_SHIFT_CONFIG_DIR', tmp_path/'cold-worker')
    assert alice.get('/api/domestic-labor/night-shift/config/202606').json()['jinjiang_list_confirmed']
    assert not bob.get('/api/domestic-labor/night-shift/config/202606').json()['jinjiang_list_confirmed']
    assert len(alice.get('/api/domestic-labor/night-shift/config/202606/history').json()['revisions']) == 1


def test_remote_completion_overrides_worker_cache(monkeypatch, tmp_path):
    run_dir = tmp_path / 'payroll_remote'
    run_dir.mkdir()
    runs._save_local_payroll_metadata(run_dir, {'id':run_dir.name,'status':'计算中','results':[]})
    latest = {'id':run_dir.name,'status':'已完成','results':[{'employee_id':'A001'}]}
    monkeypatch.setattr(runs,'domestic_labor_persistent_storage_enabled',lambda:True)
    monkeypatch.setattr(runs,'load_domestic_labor_metadata_from_persistent',lambda _:latest)
    monkeypatch.setattr(runs,'load_domestic_labor_status_from_persistent',lambda _: {'id':run_dir.name,'status':'已完成'})
    assert runs.load_payroll_status(run_dir)['status'] == '已完成'
    assert runs.load_payroll_metadata(run_dir)['results'] == latest['results']
    monkeypatch.setattr(runs,'load_domestic_labor_metadata_from_persistent',lambda _:None)
    with pytest.raises(FileNotFoundError):
        runs.load_payroll_metadata(run_dir)
