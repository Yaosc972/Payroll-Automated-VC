"""Exercise downloaded, isolated skill packages and release lifecycle invariants."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import shutil
import sys
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from bonus_platform.engine.domestic_labor import skillhub


@pytest.fixture(scope="module")
def released():
    return skillhub.sync_catalog(now="2026-10-10T12:00:00+08:00")


def payload_for(item):
    contract = item["contract"]
    employee = {field:0 for field in contract["numeric_fields"]}
    employee.update({"工号":"000001", "姓名":"测试人员", "考勤月份":"202607", "工作地区":"东莞",
        "岗位名称":"操作员", "入职日期":"2024-01-01", "最后工作日":None,
        "一级部门名称":"寮步区", "二级部门名称":"中国操作部", "办公地点是否有空调":"否",
        "排班天数":31, "实际在职工作日天数":31, "正班出勤天数":31})
    for field in contract["fields"] + contract["regional_fields"].get("东莞", []):
        employee.setdefault(field, 0)
    daily = [{"工号":"000001", "姓名":"测试人员", "出勤日期":f"2026-07-{day:02}",
        "工作状态":"正常出勤", "正班时数":8, "刷卡加班":0, "实际上班时数":8,
        "测温班次":"白班", "测温网点":"华南1号枢纽-寮步仓", "是否异常":"否", "异常原因":"",
        "上班一":"22:00", "下班一":"23:00", "班次编号":"TEST01", "班次时间段":"23:00-08:00"}
        for day in range(1, 32 if item["id"] == "quanqinjiang" else 4)]
    payload = {"month":"202607", "employees":[employee], "daily":daily, "housing":[],
        "abandonment_roster":[], "seniority_roster":[], "temperature_exclusions":[],
        "temperatures":[{"班次日期":row["出勤日期"], "测温班次":"白班", "测温网点":row["测温网点"], "测温温度":35} for row in daily],
        "night_config":{"shift_breaks":[{"shift_code":"TEST01", "effective_start_date":"2026-07-01", "break_periods":[]}], "jinjiang_list_confirmed":True},
        "sources":{}}
    sources = ["employees"] + contract["sources"] + contract.get("conditional_sources_by_area", {}).get("东莞", [])
    for source in sources:
        payload["sources"][source] = {"month":"202607", "status":"provided" if payload[source] else "confirmed_empty",
            "complete":True, "evidence":"合成测试资料：已明确本次人员与适用期间"}
    return payload


def execute_package(tmp_path, data, item, payload, mode="calculate"):
    with ZipFile(BytesIO(data)) as archive:
        archive.extractall(tmp_path)
    root = tmp_path / item["slug"]
    input_path = root / "input.json"
    output = root / "output.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False))
    subprocess.run([sys.executable, "scripts/run.py", str(input_path), "--mode", mode, "--output", str(output)],
        cwd=root, check=True, capture_output=True, text=True, timeout=30,
        env={"PATH":"/usr/bin:/bin", "PYTHONPATH":""})
    return json.loads(output.read_text())


@pytest.mark.parametrize("subject", list(skillhub.SKILLS))
def test_all_seven_downloads_run_without_platform(tmp_path, released, subject):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == subject)
    report = execute_package(tmp_path, bundles[subject], item, payload_for(item))
    assert report["status"] == "calculated", report
    assert report["rule_version"] == item["rule_version"]
    assert len(report["results"]) == 1
    assert report["results"][0]["employee_id"] == "000001"


def test_release_is_reproducible_and_unchanged_build_has_no_new_arrivals(released):
    first, bundles = released
    second, again = skillhub.sync_catalog(first, now="2026-10-11T12:00:00+08:00")
    assert second["releases"] == first["releases"]
    assert bundles == again
    assert len(second["releases"]) == 7


@pytest.mark.parametrize("conflict", [False, True])
def test_temperature_package_uses_attendance_classification_and_exposes_conflicts(tmp_path, released, conflict):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "gaowen_butie")
    payload = payload_for(item)
    for row in payload["daily"]:
        row.pop("测温班次")
        row.update({"班次分类": "夜班", "班次时间段": "17:00-26:00;"})
        if conflict:
            row["测温班次"] = "白班"
    payload["temperatures"] += [{**r, "测温班次": "夜班", "测温温度": 31} for r in list(payload["temperatures"])]
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    result = report["results"][0]
    if conflict:
        assert result["status"] == "needs_review"
        assert result["amount"] is None
        assert any(e["code"] == "HIGH_TEMPERATURE_SHIFT_CONFLICT" for e in result["details"]["exceptions"])
    else:
        assert result["status"] == "calculated"
        assert result["amount"] == 0
        assert all(row["shift"] == "夜班" for row in result["details"]["daily_results"])


def test_same_rule_version_with_changed_engine_creates_one_new_release(monkeypatch, released, tmp_path):
    catalog, _ = released
    source = tmp_path / "source"
    shutil.copytree(skillhub.ROOT, source, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(skillhub, "ROOT", source)
    engine = source / "engines/canbu.py"
    engine.write_text(engine.read_text() + "\n# independent source revision\n")
    updated, _ = skillhub.sync_catalog(catalog, now="2026-10-11T12:00:00+08:00")
    assert len(updated["releases"]) == 8
    assert updated["releases"][0]["skill_id"] == "canbu"
    again, _ = skillhub.sync_catalog(updated, now="2026-10-12T12:00:00+08:00")
    assert again["releases"] == updated["releases"]


def test_high_temperature_excludes_only_confirmed_interval_and_keeps_audit(tmp_path, released):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "gaowen_butie")
    payload = payload_for(item)
    payload["temperature_exclusions"] = [{"工号":"000001", "姓名":"测试人员", "工作地区":"东莞",
        "不享有原因":"办公地点有空调", "生效日期":"2026-07-02", "结束日期":"2026-07-02"}]
    payload["sources"]["temperature_exclusions"]["status"] = "provided"
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] == "calculated"
    assert report["results"][0]["amount"] == 27.6
    days = report["results"][0]["details"]["daily_results"]
    assert days[1]["reason_code"] == "supplemental_period_excluded"
    assert days[1]["exclusion_reason"] == "办公地点有空调"


@pytest.mark.parametrize("problem", ["missing_roster", "empty_unconfirmed", "unknown_site", "missing_measurement", "overlap"])
def test_high_temperature_incomplete_data_cannot_be_verified_pay(tmp_path, released, problem):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "gaowen_butie")
    payload = payload_for(item)
    if problem == "missing_roster": payload.pop("temperature_exclusions")
    if problem == "empty_unconfirmed": payload["sources"]["temperature_exclusions"]["status"] = "provided"
    if problem == "unknown_site": payload["daily"][0]["测温网点"] = "业务新名称"
    if problem == "missing_measurement": payload["temperatures"].pop(0)
    if problem == "overlap":
        row = {"工号":"000001", "姓名":"测试人员", "工作地区":"东莞", "不享有原因":"办公地点有空调", "生效日期":"2026-07-01", "结束日期":None}
        payload["temperature_exclusions"] = [row, row.copy()]
        payload["sources"]["temperature_exclusions"]["status"] = "provided"
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] in {"blocked", "needs_review"}
    assert not report["results"] or report["results"][0]["amount"] is None


def test_custom_site_mapping_is_explicit_and_validated(tmp_path, released):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "gaowen_butie")
    payload = payload_for(item)
    for row in payload["daily"]: row["测温网点"] = "业务新名称"
    payload["temperature_site_mapping"] = {"业务新名称":"华南1号枢纽-寮步仓"}
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] == "calculated"
    assert report["results"][0]["amount"] == 41.4
    assert any(row["method"] == "confirmed" for row in report["supplemental_audit"]["temperature_site_matches"])


def test_validate_does_not_calculate_amounts(tmp_path, released):
    catalog, bundles = released
    item = catalog["skills"][0]
    report = execute_package(tmp_path, bundles[item["id"]], item, payload_for(item), "validate")
    assert report["status"] == "validated"
    assert "results" not in report


@pytest.mark.parametrize("subject,changes,amount", [
    ("canbu", {"工作地区":"嘉善", "岗位名称":"实习生"}, 300),
    ("yeban_butie", {}, 9),
    ("yeban_butie", {"岗位名称":"理货员"}, 0),
    ("gonglingjiang", {"工作地区":"晋江", "二级部门名称":"东南B2B枢纽组"}, 100),
])
def test_latest_business_fixes_are_present_in_standalone_skills(tmp_path, released, subject, changes, amount):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == subject)
    payload = payload_for(item)
    payload["employees"][0].update(changes)
    if subject == "canbu":
        for field in item["contract"]["regional_fields"]["嘉善"]:
            payload["employees"][0].setdefault(field, 0)
    report = execute_package(tmp_path, bundles[subject], item, payload)
    assert report["status"] == "calculated", report
    assert report["results"][0]["amount"] == amount


@pytest.mark.parametrize("problem", ["missing_roster", "empty_unconfirmed", "overlap"])
def test_housing_roster_completeness_and_conflicts_block_payment(tmp_path, released, problem):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "waisu_butie")
    payload = payload_for(item)
    if problem == "missing_roster": payload.pop("housing")
    if problem == "empty_unconfirmed": payload["sources"]["housing"]["status"] = "provided"
    if problem == "overlap":
        row = {"工号":"000001", "姓名":"测试人员", "入住时间":"2026-06-01", "退宿时间":None}
        payload["housing"] = [row, row.copy()]
        payload["sources"]["housing"]["status"] = "provided"
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] == "blocked", report
    assert report["results"] == []


def test_housing_checkout_deducts_actual_daily_leave_from_external_days(tmp_path, released):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "waisu_butie")
    payload = payload_for(item)
    payload["employees"][0]["事假时数"] = 56
    payload["housing"] = [{"工号":"000001", "姓名":"测试人员", "入住时间":"2026-07-01", "退宿时间":"2026-07-02"}]
    payload["sources"]["housing"]["status"] = "provided"
    for row in payload["daily"]:
        row.update({field:0 for field in item["contract"]["checkout_daily_fields"]})
    payload["daily"][1].update({"上班一":None, "下班一":None, "事假":8})
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] == "calculated", report
    assert report["results"][0]["details"]["退宿后外宿期间缺勤天数"] == 1
    assert report["results"][0]["amount"] == 140.32


def test_housing_low_attendance_uses_complete_punch_dates(tmp_path, released):
    catalog, bundles = released
    item = next(item for item in catalog["skills"] if item["id"] == "waisu_butie")
    payload = payload_for(item)
    payload["employees"][0].update({"工作地区":"嘉善", "正班出勤天数":1, "旷工天数":1})
    for field in item["contract"]["regional_fields"]["嘉善"]:
        payload["employees"][0].setdefault(field, 0)
    report = execute_package(tmp_path, bundles[item["id"]], item, payload)
    assert report["status"] == "calculated", report
    assert report["results"][0]["amount"] == 14.52


def test_skillhub_page_and_download_keep_domestic_module_access_gate():
    from starlette.requests import Request
    from bonus_platform.app import _domestic_labor_access_response
    for path, status in (("/domestic-labor-skillhub.html",302), ("/api/domestic-labor/skillhub",401), ("/api/domestic-labor/skillhub/canbu/download",401)):
        request = Request({"type":"http", "method":"GET", "path":path, "headers":[], "query_string":b"", "scheme":"http", "server":("testserver",80)})
        assert _domestic_labor_access_response(request).status_code == status


@pytest.mark.usefixtures("bypass_domestic_labor_access_gate")
def test_api_download_integrity_unknown_skill_and_stale_link(monkeypatch, released):
    from bonus_platform.app import app
    monkeypatch.setattr(skillhub, "current_catalog", lambda:released)
    with TestClient(app) as client:
        response = client.get("/api/domestic-labor/skillhub")
        assert len(response.json()["skills"]) == 7
        item = released[0]["skills"][0]
        response = client.get(item["download_url"])
        assert response.content == released[1][item["id"]]
        assert response.headers["content-type"] == "application/zip"
        assert client.get(f"/api/domestic-labor/skillhub/{item['id']}/download?release=old").status_code == 409
        assert client.get("/api/domestic-labor/skillhub/unknown/download").status_code == 404
        bundle = client.get("/api/domestic-labor/skillhub/bundle/download")
        with ZipFile(BytesIO(bundle.content)) as archive:
            assert len(archive.namelist()) == 7
