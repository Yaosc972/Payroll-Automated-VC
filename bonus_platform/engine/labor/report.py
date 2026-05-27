from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import LaborLineItem


REPORT_SHEETS = ["核对摘要", "金额差异员工", "工时风险项", "未匹配员工", "低置信度抽取", "PDF抽取明细", "Excel账单明细", "字段映射记录"]


def build_labor_report(
    output_path: Path,
    comparison: Dict[str, Any],
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    mapping: Dict[str, str],
) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_summary(workbook, comparison.get("summary", {}))
    rows = comparison.get("rows", [])
    _write_rows(workbook, "金额差异员工", _filter(rows, "金额差异"))
    _write_rows(workbook, "工时风险项", _filter(rows, "工时不一致"))
    _write_rows(workbook, "未匹配员工", [row for row in rows if row.get("matchStatus") in {"PDF有Excel无", "Excel有PDF无", "疑似姓名匹配"}])
    _write_rows(workbook, "低置信度抽取", [row for row in rows if row.get("matchStatus") == "低置信度抽取" or "低置信度抽取" in row.get("riskFlags", [])])
    _write_detail(workbook, "PDF抽取明细", pdf_rows)
    _write_detail(workbook, "Excel账单明细", excel_rows)
    _write_mapping(workbook, mapping)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def _write_summary(workbook: Workbook, summary: Dict[str, Any]) -> None:
    sheet = workbook.create_sheet("核对摘要")
    sheet.append(["项目", "值"])
    for key, value in summary.items():
        sheet.append([key, value])
    _format(sheet)


def _write_rows(workbook: Workbook, title: str, rows: List[Dict[str, Any]]) -> None:
    headers = ["employeeName", "matchStatus", "pdfHoursTotal", "excelHoursTotal", "hoursDelta", "pdfAmountTotal", "excelAmountTotal", "amountDelta", "riskFlags", "sourceRefs"]
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        values = []
        for header in headers:
            value = row.get(header, "")
            if isinstance(value, list):
                value = "；".join(str(item) for item in value)
            values.append(value)
        sheet.append(values)
    _format(sheet)


def _write_detail(workbook: Workbook, title: str, rows: List[LaborLineItem]) -> None:
    headers = ["source_type", "source_file", "source_page_or_row", "employee_id", "employee_name_raw", "employee_name_normalized", "hours", "amount", "currency", "confidence", "evidence_text"]
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        data = row.to_dict()
        sheet.append([data.get(header, "") for header in headers])
    _format(sheet)


def _write_mapping(workbook: Workbook, mapping: Dict[str, str]) -> None:
    sheet = workbook.create_sheet("字段映射记录")
    sheet.append(["字段", "Excel列"])
    for key, label in mapping.items():
        sheet.append([key, label])
    _format(sheet)


def _filter(rows: List[Dict[str, Any]], status: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row.get("matchStatus") == status]


def _format(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="EAF2F8")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for column in range(1, sheet.max_column + 1):
        letter = get_column_letter(column)
        width = 14
        for cell in sheet[letter]:
            width = min(max(width, len(str(cell.value or "")) + 2), 48)
        sheet.column_dimensions[letter].width = width
    sheet.freeze_panes = "A2"

