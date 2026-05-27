from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openpyxl import load_workbook

from .models import LaborLineItem
from .parsing import display_name, parse_number


NAME_KEYWORDS = ("姓名", "员工姓名", "name", "employee", "associate")
ID_KEYWORDS = ("工号", "员工id", "employee id", "employee_id", "id")
HOURS_KEYWORDS = ("时长", "工时", "hours", "hour", "time")
AMOUNT_KEYWORDS = ("费用", "金额", "合计", "amount", "total", "pay")
AMOUNT_PREFERRED_KEYWORDS = ("费用总计(含税)", "含税", "total", "amount")
CURRENCY_KEYWORDS = ("币种", "currency")


def list_workbook_sheets(path: Path) -> List[str]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    return workbook.sheetnames


def suggest_mapping(path: Path, sheet_name: str) -> Dict[str, Any]:
    sheet, rows = _sheet_rows(path, sheet_name, max_rows=21)
    if not rows:
        raise ValueError("Excel 工作表为空，无法识别字段。")
    headers = [display_name(value) for value in rows[0]]
    preview = [_row_dict(headers, row) for row in rows[1:]]
    return {
        "sheetName": sheet.title,
        "headers": headers,
        "suggestedMapping": {
            "employeeId": _employee_id_header(headers),
            "name": _first_header(headers, NAME_KEYWORDS),
            "hours": _first_header(headers, HOURS_KEYWORDS),
            "amount": _preferred_amount_header(headers) or _first_header(headers, AMOUNT_KEYWORDS),
            "currency": _first_header(headers, CURRENCY_KEYWORDS),
        },
        "previewRows": [row for row in preview if any(value not in (None, "") for value in row.values())][:20],
    }


def read_workbook_rows(path: Path, sheet_name: str, mapping: Dict[str, str]) -> List[LaborLineItem]:
    _validate_mapping(mapping)
    sheet, rows = _sheet_rows(path, sheet_name, max_rows=None)
    if not rows:
        raise ValueError("Excel 工作表为空，无法读取线下账单。")
    headers = [display_name(value) for value in rows[0]]
    index = {header: position for position, header in enumerate(headers)}
    for required in ("name", "hours", "amount"):
        if mapping[required] not in index:
            raise ValueError(f"字段映射无效：找不到 {mapping[required]}")
    result: List[LaborLineItem] = []
    for offset, row in enumerate(rows[1:], start=2):
        name = _value(row, index[mapping["name"]])
        if name in (None, ""):
            continue
        hours = parse_number(_value(row, index[mapping["hours"]]))
        amount = parse_number(_value(row, index[mapping["amount"]]))
        currency = ""
        employee_id = ""
        if mapping.get("employeeId") and mapping["employeeId"] in index:
            employee_id = display_name(_value(row, index[mapping["employeeId"]]))
        if mapping.get("currency") and mapping["currency"] in index:
            currency = display_name(_value(row, index[mapping["currency"]]))
        result.append(
            LaborLineItem(
                source_type="offline_workbook",
                source_file=path.name,
                source_page_or_row=f"{sheet.title}!{offset}",
                employee_id=employee_id,
                employee_name_raw=display_name(name),
                hours=round(hours, 2),
                amount=round(amount, 2),
                currency=currency,
                confidence=1.0,
                evidence_text="",
            )
        )
    return result


def _sheet_rows(path: Path, sheet_name: str, max_rows: int | None) -> tuple[Any, List[tuple[Any, ...]]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"找不到工作表：{sheet_name}")
    sheet = workbook[sheet_name]
    if hasattr(sheet, "reset_dimensions"):
        sheet.reset_dimensions()
    iterator = sheet.iter_rows(values_only=True, max_row=max_rows)
    rows = [row for row in iterator if any(value not in (None, "") for value in row)]
    return sheet, rows


def _first_header(headers: List[str], keywords: tuple[str, ...]) -> str:
    for header in headers:
        lowered = header.lower()
        if any(keyword.lower() in lowered for keyword in keywords):
            return header
    return ""


def _preferred_amount_header(headers: List[str]) -> str:
    for header in headers:
        if "含税" in header and "不含税" not in header:
            return header
    return _first_header(headers, AMOUNT_PREFERRED_KEYWORDS)


def _employee_id_header(headers: List[str]) -> str:
    for header in headers:
        if header in {"工号", "员工工号", "Employee ID", "employee id"}:
            return header
    for header in headers:
        lowered = header.lower()
        if "供应商" in header:
            continue
        if any(keyword.lower() in lowered for keyword in ID_KEYWORDS):
            return header
    return ""


def _row_dict(headers: List[str], row: tuple[Any, ...]) -> Dict[str, Any]:
    return {header: _value(row, index) for index, header in enumerate(headers) if header}


def _value(row: tuple[Any, ...], index: int) -> Any:
    if index >= len(row):
        return None
    return row[index]


def _validate_mapping(mapping: Dict[str, str]) -> None:
    missing = [field for field in ("name", "hours", "amount") if not mapping.get(field)]
    if missing:
        raise ValueError("字段映射缺少姓名、工时或金额，无法比对。")
