from datetime import datetime
from pathlib import Path
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from bonus_platform.app import _json_safe, _pair_recruitment_sources, app
from bonus_platform.engine.recruitment_sources import (
    DOMESTIC_OFFER,
    EHR_RESIGNATIONS,
    EHR_ROSTER,
    EXTERNAL_SUPPLEMENT,
    HISTORICAL_BASELINE,
    OEHR_RESIGNATIONS,
    OEHR_ROSTER,
    OVERSEAS_OFFER,
    SPECIAL_APPROVALS,
    inspect_recruitment_source,
    inspect_recruitment_source_package,
    source_package_error_message,
)
from bonus_platform.engine.table_data import load_table_data, save_table_data


def _workbook(path: Path, headers: list[str]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    workbook.save(path)
    return path


def _workbook_bytes(headers: list[str]) -> bytes:
    workbook = Workbook()
    workbook.active.append(headers)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_source_inspection_recognizes_each_supported_source(tmp_path):
    fixtures = {
        HISTORICAL_BASELINE: ("4月历史明细.xlsx", ["验证唯一", "姓名", "工号", "招聘负责人入职奖金明细", "周期天数剔除"]),
        EHR_ROSTER: ("EHR花名册.xlsx", ["JobNumber", "parent_Name", "EmployeeStatus", "EntryDate", "parent_IDNumber", "OIdJobLevel"]),
        OEHR_ROSTER: ("OEHR花名册.xlsx", ["姓名", "工号", "offer流程编号", "人员状态", "入职日期", "证件号码", "二级部门"]),
        DOMESTIC_OFFER: ("国内offer.xlsx", ["LookupPrefix_LURecord_JobNumber", "LookupPrefix_RecruitmentRequirement_extzhiweifenlei_109025_933701443", "LookupPrefix_RecruitmentRequirement_CreateDate", "ApprovalStatus"]),
        OVERSEAS_OFFER: ("海外offer.xlsx", ["offer编码", "招聘需求编码", "编制ABC分类", "招聘负责人工号", "其他渠道", "状态"]),
        EHR_RESIGNATIONS: ("ehr离职.xlsx", ["JobNumber", "LastWorkDate", "ChangeReason", "TransitionTypeOID", "ApprovalStatus"]),
        OEHR_RESIGNATIONS: ("oehr离职.xlsx", ["标题", "工号", "最后工作日", "离职类型", "审批状态", "是否作废"]),
        SPECIAL_APPROVALS: ("特殊事项审批.xlsx", ["事项分类", "申请单编号", "申请说明", "招聘周期特殊剔除时间（天）", "文档状态"]),
    }

    for expected_role, (filename, headers) in fixtures.items():
        path = _workbook(tmp_path / filename, headers)
        inspection = inspect_recruitment_source(path)
        assert inspection.role == expected_role
        assert inspection.confidence in {"high", "medium"}


def test_source_package_requires_explicit_baseline_and_core_sources(tmp_path):
    files = [
        ("EHR花名册.xlsx", _workbook(tmp_path / "ehr.xlsx", ["JobNumber", "parent_Name", "EmployeeStatus", "EntryDate", "parent_IDNumber"])),
        ("OEHR花名册.xlsx", _workbook(tmp_path / "oehr.xlsx", ["姓名", "工号", "offer流程编号", "人员状态", "入职日期", "证件号码"])),
    ]

    package = inspect_recruitment_source_package(files)

    assert package["ready"] is False
    missing = {row["role"] for row in package["missingRoles"]}
    assert HISTORICAL_BASELINE in missing
    assert DOMESTIC_OFFER in missing
    assert OVERSEAS_OFFER in missing
    assert "可信历史基线" in source_package_error_message(package)


def test_source_package_rejects_duplicate_roles(tmp_path):
    headers = ["offer编码", "招聘需求编码", "编制ABC分类", "招聘负责人工号", "其他渠道"]
    package = inspect_recruitment_source_package([
        ("海外offer一.xlsx", _workbook(tmp_path / "one.xlsx", headers)),
        ("海外offer二.xlsx", _workbook(tmp_path / "two.xlsx", headers)),
    ])

    assert package["ready"] is False
    assert package["duplicateRoles"][0]["role"] == OVERSEAS_OFFER
    assert "重复来源" in source_package_error_message(package)


def test_source_package_does_not_silently_ignore_external_supplement(tmp_path):
    package = inspect_recruitment_source_package([
        (
            "体系外补充.xlsx",
            _workbook(
                tmp_path / "external.xlsx",
                ["体系外人员编号", "数据动作", "招聘负责人工号", "入职日期", "姓名"],
            ),
        )
    ])

    assert package["ready"] is False
    assert package["unsupportedRoles"][0]["role"] == EXTERNAL_SUPPLEMENT
    assert "尚未建立可验证的字段映射" in source_package_error_message(package)


def test_source_package_api_blocks_calculation_without_trusted_baseline():
    client = TestClient(app)

    response = client.post(
        "/api/recruitment/source-packages/calculate",
        data={"month": "202605"},
        files=[
            (
                "files",
                ("EHR花名册.xlsx", _workbook_bytes(["JobNumber", "parent_Name", "EmployeeStatus", "EntryDate", "parent_IDNumber"]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            )
        ],
    )

    assert response.status_code == 400
    assert "可信历史基线" in response.json()["detail"]


def test_source_package_pairing_is_python39_compatible_and_strict():
    saved_sources = [("EHR花名册.xlsx", Path("/tmp/ehr.xlsx"))]
    inspections = [{"role": EHR_ROSTER}]

    assert _pair_recruitment_sources(saved_sources, inspections) == [(saved_sources[0], inspections[0])]

    try:
        _pair_recruitment_sources(saved_sources, [])
    except ValueError as exc:
        assert "数量不一致" in str(exc)
    else:
        raise AssertionError("来源文件与识别结果数量不一致时必须失败")


def test_recruitment_metadata_serializes_dates_before_persistence():
    value = {"待确认": [{"发放对象最后工作日": datetime(2026, 5, 20)}]}

    assert _json_safe(value) == {"待确认": [{"发放对象最后工作日": "2026-05-20T00:00:00"}]}


def test_recruitment_table_data_persists_pending_dates(tmp_path):
    save_table_data(tmp_path, {"rows": [{"calculation": {"pending": {"最后工作日": datetime(2026, 5, 20)}}}]})

    assert load_table_data(tmp_path)["rows"][0]["calculation"]["pending"]["最后工作日"] == "2026-05-20T00:00:00"
