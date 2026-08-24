from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bonus_platform.app import app
from bonus_platform.engine.social_insurance import field_metadata
from bonus_platform.engine.social_insurance.field_metadata import ENUM_OPTIONS, FIELD_DEFINITION_BY_NAME
from bonus_platform.engine.social_insurance.runs import RunValidationError, create_run, update_employee


BASE_REPORT = {
    "证件号码": "TEST-ID-META-001",
    "姓名": "字段控件测试员工",
    "户籍": "广东省外户籍",
    "入深户时间": "",
    "民族": "汉族",
    "手机号码": "13000000000",
    "通讯地址": "深圳市测试地址",
    "电脑号": "",
    "岗位类别": "管理(技术)岗位",
    "个人身份": "干部",
    "用工形式": "合同工",
    "学历": "大学本科",
    "职称": "无",
    "国家职业资格或职业技能等级": "无",
    "医疗缴费档次": "职工二档",
    "部门名称": "",
    "户籍地类别": "农业",
    "户口所在地行政区划代码": "450801.市辖区",
    "就业形式": "雇佣就业",
    "就业前身份": "其他",
}


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path))
    return create_run(
        records=[{
            "status": "ready",
            "report": BASE_REPORT,
            "entryDate": "2026-08-10",
            "source": {"subject": "深圳市前海云途物流有限公司", "place": "深圳", "employType": "内部员工"},
        }],
        period_start="2026-07-16",
        period_end="2026-08-15",
        subject="深圳市前海云途物流有限公司",
        source="fixture",
    )


def test_field_controls_and_enums_match_government_template():
    assert FIELD_DEFINITION_BY_NAME["入深户时间"]["control"] == "date"
    assert FIELD_DEFINITION_BY_NAME["户口所在地行政区划代码"]["control"] == "adminDivision"
    assert FIELD_DEFINITION_BY_NAME["通讯地址"]["control"] == "text"
    assert ENUM_OPTIONS["户籍"] == ("深圳户籍", "广东省内非深户", "广东省外户籍")
    assert ENUM_OPTIONS["岗位类别"] == ("工人岗位", "管理(技术)岗位")
    assert ENUM_OPTIONS["学历"] == (
        "博士研究生", "硕士研究生", "大学本科", "大学专科", "中等专科",
        "职业高中", "技工学校", "普通中学（高中）", "初级中学", "小学",
    )
    assert ENUM_OPTIONS["就业形式"] == ("雇佣就业", "派遣就业")
    assert ENUM_OPTIONS["就业前身份"][-1] == "其他"
    assert len(ENUM_OPTIONS["民族"]) == 57


def test_invalid_enum_value_is_rejected_server_side(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run = _run(tmp_path, monkeypatch)
    employee_id = run["employees"][0]["id"]

    with pytest.raises(RunValidationError, match="学历必须从政务模板枚举选择"):
        update_employee(run["id"], employee_id, {"report": {"学历": "本科"}})


def test_unknown_administrative_division_is_rejected_server_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        field_metadata,
        "load_administrative_divisions",
        lambda: ["450801.市辖区", "450802.港北区"],
    )
    run = _run(tmp_path, monkeypatch)
    employee_id = run["employees"][0]["id"]

    with pytest.raises(RunValidationError, match="行政区划代码必须从政务模板区县字典选择"):
        update_employee(
            run["id"],
            employee_id,
            {"report": {"户口所在地行政区划代码": "999999.不存在区"}},
        )


def test_metadata_api_returns_template_options_without_local_paths(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        field_metadata,
        "load_administrative_divisions",
        lambda: ["450801.市辖区", "450802.港北区"],
    )
    monkeypatch.setattr(
        field_metadata,
        "load_administrative_division_choices",
        lambda: [
            {"value": "450801.市辖区", "context": "广西壮族自治区 / 贵港市", "searchText": "广西壮族自治区 贵港市 450801 市辖区"},
            {"value": "450802.港北区", "context": "广西壮族自治区 / 贵港市", "searchText": "广西壮族自治区 贵港市 450802 港北区"},
        ],
    )

    response = TestClient(app).get("/api/social-insurance/metadata")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "government-template-schema-registry"
    assert len(payload["schemas"]) == 8
    assert {schema["route"] for schema in payload["schemas"]} >= {
        "shenzhen-social-medical", "zhejiang-social-medical", "chengdu-medical",
    }
    assert payload["administrativeDivisions"] == ["450801.市辖区", "450802.港北区"]
    assert payload["administrativeDivisionChoices"][0]["context"].endswith("贵港市")
    education = next(item for item in payload["fields"] if item["name"] == "学历")
    assert education["control"] == "select"
    assert education["options"][3] == "大学专科"
    assert "/Users/" not in response.text


def test_administrative_division_search_choices_include_parent_city():
    values, choices = field_metadata._build_administrative_division_metadata([
        "45.广西壮族自治区",
        "4508.贵港市",
        "450801.市辖区",
        "450802.港北区",
    ])

    assert values == ["450801.市辖区", "450802.港北区"]
    assert choices[0]["value"] == "450801.市辖区"
    assert choices[0]["context"] == "广西壮族自治区 / 贵港市"
    assert "贵港市" in choices[0]["searchText"]


def test_vercel_runtime_uses_bundled_administrative_divisions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_ENGINE_DIR", raising=False)
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_TEMPLATE_FILE", raising=False)
    monkeypatch.setattr(
        field_metadata.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Vercel metadata must not invoke the local Node bridge"),
    )

    values = field_metadata.load_administrative_divisions()
    choices = field_metadata.load_administrative_division_choices()

    assert len(values) > 3_000
    assert "450801.市辖区" in values
    assert len(choices) == len(values)
    assert any(item["context"].endswith("贵港市") for item in choices if item["value"] == "450801.市辖区")


def test_employee_drawer_uses_metadata_driven_controls():
    static_dir = Path(__file__).resolve().parents[1] / "bonus_platform" / "static"
    script = (static_dir / "social-insurance.js").read_text(encoding="utf-8")

    assert "/api/social-insurance/metadata" in script
    assert "field.control === 'select'" in script
    assert "field.control === 'adminDivision'" in script
    assert "input.type = 'date'" in script
