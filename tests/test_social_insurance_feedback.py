from copy import deepcopy
from io import BytesIO

from openpyxl import load_workbook
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bonus_platform.engine.social_insurance import report, runs
from bonus_platform.engine.social_insurance import router as social_router
from bonus_platform.engine.social_insurance.report_package import build_export_preflight
from tests.test_social_insurance_mvp import _record


def test_all_subject_export_keeps_subjects_decisions_and_period(monkeypatch):
    contexts = {
        "a": {"subject": "甲公司", "periodStart": "2026-07-16", "periodEnd": "2026-08-15", "confirmationDate": "2026-08-16"},
        "b": {"subject": "乙公司", "periodStart": "2026-07-16", "periodEnd": "2026-08-15", "confirmationDate": "2026-08-16"},
    }
    for key, context in contexts.items():
        employee = {"report": {"姓名": key}, "source": {}, "decision": "include" if key == "a" else "exclude"}
        context["employees"] = [employee]
    monkeypatch.setattr(report, "load_run", lambda run_id, **kwargs: deepcopy(contexts[run_id]))
    release = {**contexts["a"], "subjects": [{"runId": "a", "value": "甲公司"}, {"runId": "b", "value": "乙公司"}]}
    workbook = load_workbook(BytesIO(report.build_all_subject_audit_export(release)))
    rows = list(workbook.active.values)
    headers = list(rows[3])
    assert [row[headers.index("合同主体")] for row in rows[4:]] == ["甲公司", "乙公司"]
    assert [row[headers.index("处理结果")] for row in rows[4:]] == ["纳入", "排除"]
    contexts["b"]["confirmationDate"] = "2026-08-17"
    with pytest.raises(runs.RunValidationError, match="确认日"):
        report.build_all_subject_audit_export(release)


def test_confirmation_only_reads_and_saves_the_batch_document(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path))
    run = runs.create_run(records=[_record(identity="TEST-001", name="测试人员")], period_start="2026-07-16", period_end="2026-08-15", subject="测试主体", source="fixture")
    original_load = runs.load_run
    loads = []
    def load(run_id, *, document_only=False):
        loads.append(document_only)
        return original_load(run_id, document_only=document_only)
    monkeypatch.setattr(runs, "load_run", load)
    monkeypatch.setattr(runs, "_persist_run", lambda run_id: pytest.fail("确认名单不应上传模板和导出文件"))
    saved = []
    monkeypatch.setattr(runs, "_persist_run_document", saved.append)
    result = runs.confirm_run(run["id"])
    assert result["status"] == "confirmed"
    assert loads == [True]
    assert saved == [run["id"]]


def test_preflight_recognizes_persisted_upload_without_restoring_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path))
    record = _record(identity="TEST-001", name="测试人员")
    record["coverageSource"] = {"socialPlace": "深圳", "socialMedicalStatus": "社保待审核，医保待审核"}
    run = runs.create_run(records=[record], period_start="2026-07-16", period_end="2026-08-15", subject="测试主体", source="fixture")
    run["templates"] = {"shenzhen-social-medical": {"filename": "government-template-shenzhen-social-medical.xlsx", "originalFilename": "深圳模板.xlsx", "size": 100}}
    preflight = build_export_preflight(run)
    assert preflight["groups"][0]["template"]["source"] == "uploaded"
    assert preflight["groups"][0]["ready"] is True


def test_all_subject_download_enforces_access_and_returns_attachment(monkeypatch):
    app = FastAPI()
    app.include_router(social_router.router)
    def denied(_request):
        raise HTTPException(status_code=403, detail="无权限")
    monkeypatch.setattr(social_router, "_require_access", denied)
    client = TestClient(app)
    url = "/api/social-insurance/releases/release_20260910000000_12345678/audit-export"
    assert client.get(url).status_code == 403
    monkeypatch.setattr(social_router, "_require_access", lambda request: None)
    monkeypatch.setattr(social_router, "load_reporting_release", lambda release_id: {"periodStart": "2026-07-16", "periodEnd": "2026-08-15"})
    monkeypatch.setattr(social_router, "build_all_subject_audit_export", lambda release: b"workbook")
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"workbook"
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    monkeypatch.setattr(social_router, "load_reporting_release", lambda release_id: None)
    assert client.get(url).status_code == 404


def test_all_subject_view_keeps_duplicate_employee_ids_in_their_own_subject(monkeypatch):
    release = {"id": "release_test", "periodStart": "2026-07-16", "periodEnd": "2026-08-15", "confirmationDate": "2026-08-16"}
    subjects = [
        {"id": "run_a", "subject": "甲主体", "employees": [{"id": "same_employee", "status": "ready", "decision": "include", "source": {}}]},
        {"id": "run_b", "subject": "乙主体", "employees": [{"id": "same_employee", "status": "needs_review", "decision": "include", "source": {}}]},
        {"id": "run_empty", "subject": "空主体", "employees": []},
    ]
    monkeypatch.setattr(report, "load_release_subject_runs", lambda release: subjects)
    view = report.build_all_subject_view(release)
    assert view["isAggregate"] is True
    assert view["subjectCount"] == 3
    assert view["summary"] == {"total": 2, "ready": 1, "needsReview": 1, "included": 2, "excluded": 0}
    assert [item["subjectRunId"] for item in view["employees"]] == ["run_a", "run_b"]
    assert [item["source"]["subject"] for item in view["employees"]] == ["甲主体", "乙主体"]
    assert subjects[0]["employees"][0]["source"] == {}


def test_all_subject_view_endpoint_is_read_only_and_requires_access(monkeypatch):
    app = FastAPI()
    app.include_router(social_router.router)
    client = TestClient(app)
    url = "/api/social-insurance/releases/release_20260910000000_12345678/runs/all"
    def denied(_request):
        raise HTTPException(status_code=403, detail="无权限")
    monkeypatch.setattr(social_router, "_require_access", denied)
    assert client.get(url).status_code == 403
    monkeypatch.setattr(social_router, "_require_access", lambda request: None)
    monkeypatch.setattr(social_router, "load_reporting_release", lambda release_id: {"id": release_id})
    monkeypatch.setattr(social_router, "build_all_subject_view", lambda release: {"isAggregate": True})
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["run"]["isAggregate"] is True
    assert response.headers["cache-control"] == "no-store"
    assert client.post(url).status_code == 405
