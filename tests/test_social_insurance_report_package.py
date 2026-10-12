from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import zipfile

from openpyxl import Workbook, load_workbook
import pytest

from bonus_platform.engine.social_insurance.report import store_template
from bonus_platform.engine.social_insurance.report_package import (
    build_export_preflight,
    _fill_template,
    build_missing_export,
    generate_report_package,
    resolve_package_download,
)
from bonus_platform.engine.social_insurance.runs import confirm_run, create_run
from bonus_platform.engine.social_insurance.template_library import match_template
from bonus_platform.engine.social_insurance.template_schemas import TEMPLATE_SCHEMAS
from tests.test_social_insurance_mvp import _record


def _shenzhen_record(*, identity: str = "440305199001011234", name: str = "模板测试员工") -> dict:
    record = _record(identity=identity, name=name)
    record["coverageSource"] = {
        "socialPlace": "深圳",
        "socialMedicalStatus": "社保待审核，医保待审核",
    }
    return record


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: dict) -> dict:
    runs = tmp_path / "runs"
    library = tmp_path / "template-library"
    library.mkdir()
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(runs))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_TEMPLATE_LIBRARY_DIR", str(library))
    return create_run(
        records=[record],
        period_start="2026-07-16",
        period_end="2026-08-15",
        confirmation_date="2026-08-20",
        subject="深圳市前海云途物流有限公司",
        source="fixture",
    )


def _template_bytes(route: str) -> bytes:
    schema = TEMPLATE_SCHEMAS[route]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = schema["sheet"]
    if route == "shenzhen-social-medical":
        sheet["A1"] = "单位编号"
        sheet["B1"] = "100000"
    for column, field in enumerate(schema["fields"], start=1):
        sheet.cell(row=schema["headerRow"], column=column, value=field["header"])
        sheet.cell(row=schema["dataStartRow"], column=column).number_format = "@"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_shenzhen_current_template_preserves_19_columns_and_unit_number(tmp_path: Path):
    route = "shenzhen-social-medical"
    fields = [field for field in TEMPLATE_SCHEMAS[route]["fields"] if field["name"] != "个人身份"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = TEMPLATE_SCHEMAS[route]["sheet"]
    sheet["A1"] = "单位编号"
    sheet["B1"] = "572226"
    for column, field in enumerate(fields, start=1):
        sheet.cell(row=2, column=column, value=field["header"])
    source = tmp_path / "current-template.xlsx"
    workbook.save(source)
    workbook.close()
    values = {field["name"]: f"value-{field['name']}" for field in fields}
    values["个人身份"] = "干部"
    employee = {"templateReports": {route: {"values": values}}}

    result = _fill_template(source, route, [employee], tmp_path)

    output = load_workbook(result, data_only=True)
    sheet = output[TEMPLATE_SCHEMAS[route]["sheet"]]
    assert sheet["B1"].value == "572226"
    assert sheet.max_column == 19
    assert [cell.value for cell in sheet[2]] == [field["header"] for field in fields]
    assert [cell.value for cell in sheet[3]] == [values[field["name"]] for field in fields]
    assert "干部" not in [cell.value for cell in sheet[3]]
    output.close()


def test_shenzhen_template_without_unit_number_is_rejected(tmp_path: Path):
    route = "shenzhen-social-medical"
    source = tmp_path / "template.xlsx"
    source.write_bytes(_template_bytes(route))
    workbook = load_workbook(source)
    workbook.active["B1"] = None
    workbook.save(source)
    workbook.close()
    with pytest.raises(ValueError, match="单位编号"):
        _fill_template(source, route, [], tmp_path)


def test_template_registry_preserves_exact_field_order_for_all_offline_routes():
    assert len(TEMPLATE_SCHEMAS) == 8
    assert [field["name"] for field in TEMPLATE_SCHEMAS["shenzhen-social-medical"]["fields"]][:7] == [
        "证件号码", "姓名", "户籍", "入深户时间", "民族", "手机号码", "通讯地址",
    ]
    assert len(TEMPLATE_SCHEMAS["shenzhen-social-medical"]["fields"]) == 20
    assert len(TEMPLATE_SCHEMAS["zhejiang-social-medical"]["fields"]) == 21
    assert len(TEMPLATE_SCHEMAS["chengdu-medical"]["fields"]) == 22


def test_configured_shenzhen_template_is_trusted_even_without_subject_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    library = tmp_path / "template-library"
    library.mkdir()
    configured = tmp_path / "current-government-template.xls"
    configured.write_bytes(b"configured-template")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_TEMPLATE_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_TEMPLATE_FILE", str(configured))

    matched = match_template("shenzhen-social-medical", "深圳易可达科技有限公司")

    assert matched is not None
    assert matched["filename"] == configured.name
    assert matched["matchQuality"] == "configured"
    assert matched["subjectMatched"] is True


def test_preflight_groups_missing_required_fields_by_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    record = _shenzhen_record()
    record["report"] = deepcopy(record["report"])
    record["report"]["户口所在地行政区划代码"] = ""
    run = _run(tmp_path, monkeypatch, record)

    preflight = build_export_preflight(run["id"])

    assert preflight["summary"]["templateRoutes"] == 1
    assert preflight["summary"]["blockedRoutes"] == 1
    group = preflight["groups"][0]
    assert group["route"] == "shenzhen-social-medical"
    assert group["status"] == "missing-fields"
    assert group["missingEmployees"] == 1
    assert group["missingFields"] == [{"field": "户口所在地行政区划代码", "count": 1}]

    workbook = load_workbook(build_missing_export(run["id"]), read_only=True, data_only=True)
    sheet = workbook["待补资料"]
    assert sheet["F2"].value == "户口所在地行政区划代码"
    assert sheet["D2"].value is None
    workbook.close()


def test_confirmed_run_generates_route_workbook_and_review_materials_in_one_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    route = "shenzhen-social-medical"
    run = _run(tmp_path, monkeypatch, _shenzhen_record(name="完整字段员工"))
    run = confirm_run(run["id"])
    run = store_template(run["id"], "深圳当前版模板.xlsx", _template_bytes(route), route=route)

    preflight = build_export_preflight(run["id"])
    assert preflight["summary"] == {
        "templateRoutes": 1,
        "readyRoutes": 1,
        "blockedRoutes": 0,
        "manualRoutes": 0,
        "employeeCount": 1,
    }
    assert preflight["groups"][0]["template"]["source"] == "uploaded"

    generated = generate_report_package(run["id"])
    package = generated["reportPackage"]
    assert package["partial"] is False
    assert package["generatedRoutes"][0]["route"] == route

    with zipfile.ZipFile(resolve_package_download(run["id"])) as archive:
        names = archive.namelist()
        report_name = next(name for name in names if name.startswith("报盘文件/") and name.endswith(".xlsx"))
        assert "审核资料/待补资料.xlsx" in names
        assert any(name.startswith("审核资料/社保增员审核清单_") for name in names)
        assert "生成说明.xlsx" in names
        workbook = load_workbook(BytesIO(archive.read(report_name)), read_only=True, data_only=True)
        sheet = workbook[TEMPLATE_SCHEMAS[route]["sheet"]]
        assert sheet.cell(row=TEMPLATE_SCHEMAS[route]["dataStartRow"], column=2).value == "完整字段员工"
        workbook.close()


def test_subject_account_persists_across_periods_and_is_isolated(tmp_path, monkeypatch):
    from bonus_platform.engine.social_insurance.subject_settings import read_settings, save_settings
    from bonus_platform.engine.social_insurance.runs import RunValidationError
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_RUNS_DIR', str(tmp_path))
    run = {'id': 'sir_test_001', 'subject': '深圳易可达科技有限公司'}
    assert read_settings(run)['unitNumber'] == '572226'
    save_settings(run, '001234')
    assert read_settings({**run, 'id': 'sir_test_002'})['unitNumber'] == '001234'
    assert read_settings({**run, 'subject': '其他主体'})['unitNumber'] == ''
    with pytest.raises(RunValidationError):
        save_settings(run, '=1+2')


def test_configured_account_fills_blank_template_without_changing_original(tmp_path):
    route = 'shenzhen-social-medical'
    source = tmp_path / 'source.xlsx'
    source.write_bytes(_template_bytes(route))
    workbook = load_workbook(source)
    workbook.active['B1'] = None
    workbook.save(source)
    workbook.close()
    output_dir = tmp_path / 'generated'
    output_dir.mkdir()
    output = _fill_template(source, route, [], output_dir, '572226')
    workbook = load_workbook(output)
    assert workbook.active['B1'].value == '572226'
    workbook.close()
    workbook = load_workbook(source)
    assert workbook.active['B1'].value is None
    workbook.close()


def test_actual_template_enums_and_reordered_columns(tmp_path):
    from openpyxl.worksheet.datavalidation import DataValidation
    route = 'shenzhen-social-medical'
    source = tmp_path / 'new.xlsx'
    source.write_bytes(_template_bytes(route))
    book = load_workbook(source)
    sheet = book.active
    # Rename/order variations with the same verified semantic meaning.
    sheet['A2'], sheet['B2'] = sheet['B2'].value, sheet['A2'].value
    dv = DataValidation(type='list', formula1='"工人,管理人员"')
    sheet.add_data_validation(dv); dv.add('I3:I1002')
    book.save(source); book.close()
    fields = TEMPLATE_SCHEMAS[route]['fields']
    values = {f['name']: '测试' for f in fields}
    values['岗位类别'] = '管理(技术)岗位'
    values['姓名'] = '模板校验'
    values['证件号码'] = 'TEST-ID'
    employees = [{'templateReports': {route: {'values': values}}}]
    output = _fill_template(source, route, employees, tmp_path, '572226')
    book = load_workbook(output)
    sheet = book.active
    start = TEMPLATE_SCHEMAS[route]['dataStartRow']
    assert sheet.cell(start,1).value == '模板校验'
    assert sheet.cell(start,2).value == 'TEST-ID'
    assert sheet.cell(start,9).value == '管理人员'
    book.close()
    book = load_workbook(source)
    book.active.data_validations.dataValidation[0].formula1 = '"未知新类别"'
    book.save(source); book.close()
    from bonus_platform.engine.social_insurance.runs import RunValidationError
    with pytest.raises(RunValidationError, match='下拉值不匹配'):
        _fill_template(source,route,employees,tmp_path,'572226')
    book = load_workbook(source)
    book.active['U2'] = '新必填业务字段'
    book.save(source); book.close()
    with pytest.raises(RunValidationError, match='未知变化'):
        _fill_template(source,route,employees,tmp_path,'572226')


def test_dotnet_timestamp_confirmation_recalculation():
    from bonus_platform.engine.social_insurance.sync_snapshot import _confirmation_decision
    context = {'currentEntryDate':'2026-09-07','dimissionRecords':[{
        'lastWorkDate':'2026-10-13','voluntaryStopFlag':'非自愿停保',
        'processCreatedTime':'2026-10-09T17:27:06.4670000+08:00',
        'processTimeReliable':True,'source':'beisen-dimission-record'}]}
    assert _confirmation_decision(context,confirmation_date='2026-09-16')[0] == 'include'
    assert _confirmation_decision(context,confirmation_date='2026-10-10')[0] == 'include'
    context['dimissionRecords'][0]['voluntaryStopFlag']='自愿停保'
    assert _confirmation_decision(context,confirmation_date='2026-10-10')[0] == 'exclude'


def test_validation_problem_list_repair_and_generation(tmp_path, monkeypatch):
    from bonus_platform.engine.social_insurance.report_package import validate_report_package
    from bonus_platform.engine.social_insurance.runs import load_run, save_run, RunNotFoundError
    from bonus_platform.engine.social_insurance.report import resolve_download
    route='shenzhen-social-medical'
    run=_run(tmp_path,monkeypatch,_shenzhen_record())
    run=confirm_run(run['id'])
    run=store_template(run['id'],'深圳模板.xlsx',_template_bytes(route),route=route)
    good=generate_report_package(run['id'])
    filename=good['reportPackage']['generatedRoutes'][0]['filename']
    assert resolve_download(run['id'],filename).is_file()
    run=load_run(run['id'])
    run['employees'][0]['report']['手机号码']=''
    save_run(run)
    checked=validate_report_package(run['id'])
    assert not checked['reportValidation']['passed']
    item=next(i for i in checked['reportValidation']['issues'] if i.get('field')=='手机号码')
    assert item['employeeId']==run['employees'][0]['id']
    assert item['action']=='employee'
    assert checked['reportPackage'] is None
    with pytest.raises(RunNotFoundError):resolve_download(run['id'],filename)
    run=load_run(run['id']);run['employees'][0]['report']['手机号码']='13800000000';save_run(run)
    assert validate_report_package(run['id'])['reportValidation']['passed']
    assert generate_report_package(run['id'])['reportPackage']['generatedRoutes']


def test_unknown_template_blocks_package_with_actionable_issue(tmp_path, monkeypatch):
    from bonus_platform.engine.social_insurance.report_package import validate_report_package
    route='shenzhen-social-medical'
    run=_run(tmp_path,monkeypatch,_shenzhen_record())
    run=confirm_run(run['id'])
    book=load_workbook(BytesIO(_template_bytes(route)))
    book.active['U2']='未知必填项'
    buffer=BytesIO();book.save(buffer);book.close()
    run=store_template(run['id'],'新版.xlsx',buffer.getvalue(),route=route)
    result=generate_report_package(run['id'])
    assert result['reportPackage'] is None
    assert not result['reportValidation']['passed']
    assert result['reportValidation']['issues'][0]['action']=='template'
    assert '未知' in result['reportValidation']['issues'][0]['message']


def test_missing_subject_account_has_configuration_action(tmp_path, monkeypatch):
    from bonus_platform.engine.social_insurance.report_package import validate_report_package
    from bonus_platform.engine.social_insurance.subject_settings import save_settings
    route='shenzhen-social-medical'
    run=_run(tmp_path,monkeypatch,_shenzhen_record())
    book=load_workbook(BytesIO(_template_bytes(route)));book.active['B1']=None
    buffer=BytesIO();book.save(buffer);book.close()
    run=store_template(run['id'],'空账号模板.xlsx',buffer.getvalue(),route=route)
    result=validate_report_package(run['id'])
    assert result['reportValidation']['issues'][0]['action']=='subject'
    save_settings(run,'123456')
    assert validate_report_package(run['id'])['reportValidation']['passed']
