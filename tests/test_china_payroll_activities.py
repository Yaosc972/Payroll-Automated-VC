"""Activity isolation, resumable jobs, uploads and backwards-compatible history."""
import asyncio
import sys
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from openpyxl import Workbook

import bonus_platform.app as app_module
from bonus_platform.engine.china_employee_payroll import activities, meal_runs, relocation_router
from bonus_platform.engine.china_employee_payroll.meal_allowance import ParsedAttendance, REQUIRED_COLUMNS, WX_REQUIRED_COLUMNS

BASE = "/api/china-employee-payroll/activities"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    meal = tmp_path / "meal"
    meal.mkdir()
    monkeypatch.setattr(app_module, "CHINA_EMPLOYEE_PAYROLL_RUNS_DIR", meal)
    monkeypatch.setattr(relocation_router, "RUNS_DIR", tmp_path / "relocation")
    monkeypatch.setattr(meal_runs, "_active", False)
    monkeypatch.setattr(relocation_router, "_active", False)
    row = dict.fromkeys(REQUIRED_COLUMNS, "")
    row.update({"员工": "测试员工", "工号": "zt10001", "人员状态": "在职", "二级组织": "HQU技术部", "三级组织": "技术部",
                "考勤日期": date(2026, 9, 1), "首打卡(含补签)": datetime(2026, 9, 1, 9, 10),
                "末打卡(含补签)": datetime(2026, 9, 1, 21, 5), "当前班次": "深圳灵活打卡8:30-9:10", "日期类型": "工作日"})
    def load(self, month, progress):
        return ParsedAttendance(rows=[row], headers=REQUIRED_COLUMNS, files=[], missing_columns=[])
    monkeypatch.setitem(sys.modules, "bonus_platform.engine.china_employee_payroll.meal_beisen", SimpleNamespace(BeisenMealSource=type("Source", (), {"load": load})))
    monkeypatch.setattr(relocation_router, "BeisenMonthlySource", lambda: SimpleNamespace(load=lambda month, progress: {}))
    monkeypatch.setattr(relocation_router, "calculate_relocation", lambda month, source, progress: {
        "summary": {"amount": 1000, "employeeCount": 1, "reviewCount": 0}, "results": [], "attendanceSource": {}, "warnings": []})


@pytest.fixture
def client():
    return TestClient(app_module.app)


def create(client, subject="meal-allowance", name="", **extra):
    response = client.post(BASE, json={"subject": subject, "month": "2026-09", "name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_three_subjects_share_list_and_independent_same_month_results(client):
    group = create(client, name="集团初算")
    repeat = create(client, name="集团复核")
    wx = create(client, "wx-meal-allowance")
    relocation = create(client, "relocation-allowance")
    for item in (group, relocation):
        assert client.post(f"{BASE}/{item['activityId']}/start").status_code == 200
    listed = client.get(BASE).json()
    assert listed["total"] == 4
    records = {a["activityId"]: a for a in listed["activities"]}
    assert records[group["activityId"]]["amount"] == 20
    assert records[relocation["activityId"]]["amount"] == 1000
    assert records[repeat["activityId"]]["status"] == records[wx["activityId"]]["status"] == "draft"
    assert records[group["activityId"]]["runId"] != records[relocation["activityId"]]["runId"]
    assert client.get(BASE, params={"subject": "meal-allowance", "status": "draft", "month": "2026-09", "search": "复核"}).json()["activities"] == [records[repeat["activityId"]]]
    detail = client.get(f"{BASE}/{group['activityId']}").json()
    assert detail == records[group["activityId"]]
    assert not {"results", "attendanceSource", "workerId"} & detail.keys()
    exported = client.get(f"/api/china-employee-payroll/meal-allowance/{detail['runId']}/export")
    assert exported.status_code == 200 and exported.content[:2] == b"PK"


def test_create_and_start_are_idempotent_and_completed_results_remain(client):
    key = "1" * 32
    first = create(client, requestId=key)
    assert create(client, requestId=key) == first
    assert client.post(BASE, json={"subject": "wx-meal-allowance", "month": "2026-09", "requestId": key}).status_code == 409
    initial = client.post(f"{BASE}/{key}/start").json()
    repeated = client.post(f"{BASE}/{key}/start").json()
    assert initial["runId"] == repeated["runId"]
    assert repeated["status"] == "completed" and repeated["attemptCount"] == 1
    assert len(list(app_module.CHINA_EMPLOYEE_PAYROLL_RUNS_DIR.glob("china_employee_payroll_*"))) == 1
    assert client.get(BASE).json()["total"] == 1


def test_creator_comes_from_session_and_survives_different_viewer(client, monkeypatch):
    monkeypatch.setattr(activities, "current_user_from_request", lambda request: {"user": {"id": "feishu-user-1", "name": "创建人甲", "avatarUrl": "https://example.com/avatar.png"}})
    item = create(client, creator={"userId": "forged", "name": "冒充", "avatarUrl": "https://invalid.example/forged"})
    expected = {"userId": "feishu-user-1", "name": "创建人甲", "avatarUrl": "https://example.com/avatar.png"}
    assert item["creator"] == expected
    monkeypatch.setattr(activities, "current_user_from_request", lambda request: {"user": {"id": "viewer-2", "name": "查看人乙"}})
    assert client.get(f"{BASE}/{item['activityId']}").json()["creator"] == expected
    assert client.get(BASE, params={"search": "创建人甲"}).json()["total"] == 1
    assert client.get(BASE, params={"search": "查看人乙"}).json()["total"] == 0


def test_local_and_missing_feishu_avatar_use_supplied_default(client, monkeypatch):
    monkeypatch.setattr(activities, "current_user_from_request", lambda request: None)
    local = create(client)
    assert local["creator"] == {"userId": "", "name": "本地用户", "avatarUrl": activities.DEFAULT_AVATAR}
    monkeypatch.setattr(activities, "current_user_from_request", lambda request: {"user": {"id": "f1", "name": "已登录员工", "avatarUrl": "javascript:alert(1)"}})
    signed_in = create(client)
    assert signed_in["creator"]["name"] == "已登录员工"
    assert signed_in["creator"]["avatarUrl"] == activities.DEFAULT_AVATAR


def test_running_activity_reopens_accepted_job_without_second_worker(client):
    item = create(client)
    tasks = BackgroundTasks()
    accepted = asyncio.run(activities.start_activity(item["activityId"], tasks, None))
    assert accepted["status"] == "running"
    reopened = client.get(f"{BASE}/{item['activityId']}").json()
    assert reopened["runId"] == accepted["runId"] and reopened["status"] == "running"
    duplicate = client.post(f"{BASE}/{item['activityId']}/start").json()
    assert duplicate["runId"] == accepted["runId"]
    assert len(tasks.tasks) == 1
    asyncio.run(tasks())
    assert client.get(f"{BASE}/{item['activityId']}").json()["status"] == "completed"


def test_failed_retry_keeps_activity_identity_and_hides_attempts_from_list(client, monkeypatch):
    item = create(client)
    tasks = BackgroundTasks()
    run = asyncio.run(activities.start_activity(item["activityId"], tasks, None))
    folder = app_module.CHINA_EMPLOYEE_PAYROLL_RUNS_DIR / run["runId"]
    metadata = meal_runs.read_metadata(folder)
    metadata.update(status="failed", progress="源数据未生成")
    meal_runs.save_json(folder / "metadata.json", metadata)
    monkeypatch.setattr(meal_runs, "_active", False)
    resumed = client.post(f"{BASE}/{item['activityId']}/start").json()
    assert resumed["activityId"] == item["activityId"] and resumed["runId"] != run["runId"]
    assert resumed["attemptCount"] == 2
    assert client.get(BASE).json()["total"] == 1


def wx_file():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(WX_REQUIRED_COLUMNS)
    sheet.append(WX_REQUIRED_COLUMNS)
    values = {"工号": "WX001", "姓名": "WX员工", "部门": "研发组", "组织架构": "WX-PBU技术部-研发组", "日期": datetime(2026, 9, 1),
              "人员类型": "正式", "员工状态": "在职", "上班 1 打卡时间": "09:10", "下班 1 打卡时间": "21:30", "班次": "09:10-18:10"}
    sheet.append([values.get(k, "") for k in WX_REQUIRED_COLUMNS])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_wx_draft_survives_reopen_and_upload_is_month_scoped(client):
    item = create(client, "wx-meal-allowance")
    url = f"{BASE}/{item['activityId']}"
    assert client.get(url).json()["status"] == "draft"
    assert client.post(url + "/start").status_code == 400
    bad = client.post(url + "/start", files=[("attendance_files", ("invalid.xlsx", b"invalid"))])
    assert bad.status_code == 400
    assert client.get(url).json()["status"] == "failed"
    response = client.post(url + "/start", files=[("attendance_files", ("wx.xlsx", wx_file()))])
    assert response.status_code == 200, response.text
    detail = client.get(url).json()
    assert detail["status"] == "completed" and detail["month"] == "2026-09"
    assert client.get(BASE).json()["total"] == 1


def test_legacy_history_is_unified_paginated_and_has_stable_links(client):
    for index in range(53):
        folder = app_module.CHINA_EMPLOYEE_PAYROLL_RUNS_DIR / f"china_employee_payroll_legacy_{index:03}"
        folder.mkdir()
        meal_runs.save_json(folder / "metadata.json", {"runId": folder.name, "status": "completed", "sourceType": "wx" if index % 2 else "hr", "month": "2026-08", "createdAt": f"2026-09-01T10:{index:02}:00", "summary": {"employeeCount": 1, "totalAmount": index}})
    first = client.get(BASE).json()
    assert first["total"] == 53 and len(first["activities"]) == 20
    third = client.get(BASE, params={"page": 3}).json()
    assert len(third["activities"]) == 13
    item = third["activities"][0]
    assert item["creator"]["name"] == "未记录" and item["creator"]["avatarUrl"] == activities.DEFAULT_AVATAR
    assert client.get(f"{BASE}/{item['activityId']}").json() == item
    assert client.get(BASE, params={"page": 99}).json()["page"] == 3
    assert client.get(BASE, params={"page_size": 0}).status_code == 400


def test_other_instance_is_not_failed_but_missing_snapshot_is(client):
    item = create(client, "wx-meal-allowance")
    record = activities._record(item["activityId"])
    record.update(status="running", workerId="old-process")
    activities._save(record)
    assert client.get(f"{BASE}/{item['activityId']}").json()["status"] == "running"
    record.update(runId="china_employee_payroll_missing", attempts=["china_employee_payroll_missing"])
    activities._save(record)
    assert client.get(f"{BASE}/{item['activityId']}").json()["status"] == "failed"


def test_duplicate_wx_upload_does_not_start_second_calculation(client, monkeypatch):
    item = create(client, "wx-meal-allowance")
    calls = []

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def upload(files, source, month):
            calls.append((source, month))
            entered.set()
            await release.wait()
            folder = app_module.CHINA_EMPLOYEE_PAYROLL_RUNS_DIR / "china_employee_payroll_concurrent"
            folder.mkdir()
            meal_runs.save_json(folder / "metadata.json", {"status": "completed", "sourceType": "wx", "month": month})
            return {"runId": folder.name, "status": "completed"}

        monkeypatch.setattr(app_module, "calculate_china_employee_meal_allowance", upload)
        first = asyncio.create_task(activities.start_activity(item["activityId"], BackgroundTasks(), [object()]))
        await entered.wait()
        duplicate = await activities.start_activity(item["activityId"], BackgroundTasks(), [object()])
        assert duplicate["status"] == "running" and not duplicate["runId"]
        release.set()
        completed = await first
        assert completed["status"] == "completed"

    asyncio.run(exercise())
    assert calls == [("wx", "2026-09")]


@pytest.mark.parametrize("payload", [{"subject": "unknown", "month": "2026-09"}, {"subject": "meal-allowance", "month": "2026-13"}, {"subject": "meal-allowance", "month": "2026-09", "name": "x" * 121}])
def test_invalid_activity_is_rejected(client, payload):
    assert client.post(BASE, json=payload).status_code == 400
    assert client.get(BASE).json()["total"] == 0
