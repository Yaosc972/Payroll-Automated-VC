from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import LaborLineItem


REPORT_SHEETS = ["核对结论", "质量评分", "核对摘要", "金额差异员工", "工时风险项", "不在本批发票", "姓名格式差异", "低置信度抽取", "PDF抽取明细", "Excel账单明细", "字段映射记录"]


def build_labor_report(
    output_path: Path,
    comparison: Dict[str, Any],
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    mapping: Dict[str, str],
    warehouse_comparison: Dict[str, Any] | None = None,
    extraction_quality: Dict[str, Any] | None = None,
) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)

    # 写入核对结论（第一个sheet）
    _write_conclusion(workbook, comparison.get("summary", {}), warehouse_comparison)

    # 写入质量评分（第二个sheet）
    if extraction_quality:
        _write_quality(workbook, extraction_quality)

    _write_summary(workbook, comparison.get("summary", {}))
    rows = comparison.get("rows", [])
    _write_rows(workbook, "金额差异员工", _filter(rows, "金额差异"))
    _write_rows(workbook, "工时风险项", _filter(rows, "工时不一致"))
    _write_rows(workbook, "不在本批发票", [row for row in rows if row.get("matchStatus") in {"PDF有Excel无", "Excel有PDF无", "疑似姓名匹配"}])
    _write_candidate_matches(workbook, comparison.get("candidateMatches", []))
    _write_rows(workbook, "低置信度抽取", [row for row in rows if row.get("matchStatus") == "低置信度抽取" or "低置信度抽取" in row.get("riskFlags", [])])
    _write_detail(workbook, "PDF抽取明细", pdf_rows)
    _write_detail(workbook, "Excel账单明细", excel_rows)
    _write_mapping(workbook, mapping)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def _write_conclusion(workbook: Workbook, summary: Dict[str, Any], warehouse_comparison: Dict[str, Any] | None = None) -> None:
    """Write the conclusion sheet as the first sheet."""
    sheet = workbook.create_sheet("核对结论", 0)

    # 核对结论
    conclusion_level = summary.get("conclusionLevel", "pass")
    conclusion_message = summary.get("conclusionMessage", "")
    level_display = {"pass": "通过", "warning": "需关注", "critical": "需人工复核"}.get(conclusion_level, conclusion_level)
    sheet.append(["核对结论", f"{level_display} - {conclusion_message}"])
    sheet.append([])

    # 总金额差异
    wc_summary = (warehouse_comparison or {}).get("summary", {})
    amount_delta_total = wc_summary.get("amountDeltaTotal", summary.get("amountDeltaTotal", 0))
    amount_delta_pct = abs(amount_delta_total) / max(abs(wc_summary.get("pdfAmountTotal", 0)), abs(wc_summary.get("excelAmountTotal", 0)), 1.0) * 100
    sheet.append(["总金额差异", f"${amount_delta_total:.2f} ({amount_delta_pct:.2f}%)"])
    sheet.append([])

    # 人数覆盖
    pdf_count = summary.get("pdfEmployeeCount", 0)
    excel_count = summary.get("excelEmployeeCount", 0)
    not_in_invoice = summary.get("notInInvoiceCount", 0)
    sheet.append(["PDF覆盖人数", pdf_count])
    sheet.append(["账单总人数", excel_count])
    sheet.append(["不在本批发票", f"{not_in_invoice}人"])
    sheet.append([])

    # 仓库差异归因摘要
    if warehouse_comparison and warehouse_comparison.get("rows"):
        sheet.append(["仓库差异归因摘要"])
        sheet.append(["仓库", "PDF金额", "Excel金额", "差异", "主要差异来源"])
        for row in warehouse_comparison["rows"]:
            if abs(row.get("amountDelta", 0)) >= 0.01:
                wh_id = row.get("warehouseId", "")
                pdf_amount = row.get("pdfAmountTotal", 0)
                excel_amount = row.get("excelAmountTotal", 0)
                delta = row.get("amountDelta", 0)
                attribution = row.get("attribution", [])
                attr_summary = "；".join([f"{a['employeeName']}: ${a['delta']:.2f}" for a in attribution[:3]])
                sheet.append([f"仓库{wh_id}", f"${pdf_amount:.2f}", f"${excel_amount:.2f}", f"${delta:.2f}", attr_summary])

    _format(sheet)


def _write_quality(workbook: Workbook, extraction_quality: Dict[str, Any]) -> None:
    """Write the quality scoring sheet."""
    sheet = workbook.create_sheet("质量评分", 1)

    # 质量级别
    level = extraction_quality.get("level", "ok")
    level_display = {"ok": "通过", "warning": "需关注", "critical": "需人工复核"}.get(level, level)
    message = extraction_quality.get("message", "")
    sheet.append(["质量级别", f"{level_display} - {message}"])
    sheet.append([])

    # 质量问题列表
    issues = extraction_quality.get("issues", [])
    if issues:
        sheet.append(["质量问题"])
        for i, issue in enumerate(issues, 1):
            sheet.append([f"{i}.", issue])
        sheet.append([])

    # 详细指标
    metrics = extraction_quality.get("metrics", {})

    # 置信度分布
    confidence = metrics.get("confidence", {})
    if confidence:
        sheet.append(["置信度分布"])
        sheet.append(["平均置信度", f"{confidence.get('average', 0):.3f}"])
        sheet.append(["低置信度记录数 (<0.85)", confidence.get("lowCount", 0)])
        sheet.append(["极低置信度记录数 (<0.5)", confidence.get("veryLowCount", 0)])
        sheet.append(["总记录数", confidence.get("totalCount", 0)])
        sheet.append([])

    # 抽取方法统计
    methods = metrics.get("extractionMethods", {})
    if methods:
        sheet.append(["抽取方法统计"])
        sheet.append(["规则抽取", methods.get("rule", 0)])
        sheet.append(["AI文本抽取", methods.get("ai_text", 0)])
        sheet.append(["AI图片抽取", methods.get("ai_image", 0)])
        sheet.append([])

    # 员工数量对比
    employee_counts = metrics.get("employeeCounts", {})
    if employee_counts:
        sheet.append(["员工数量对比"])
        sheet.append(["PDF员工数", employee_counts.get("pdf", 0)])
        sheet.append(["Excel员工数", employee_counts.get("excel", 0)])
        sheet.append(["PDF未匹配", employee_counts.get("unmatchedPdf", 0)])
        sheet.append(["Excel未匹配", employee_counts.get("unmatchedExcel", 0)])
        sheet.append([])

    # 金额/工时偏差
    totals = metrics.get("totals", {})
    if totals:
        sheet.append(["金额/工时偏差"])
        sheet.append(["PDF总工时", f"{totals.get('pdfHours', 0):.2f}"])
        sheet.append(["Excel总工时", f"{totals.get('excelHours', 0):.2f}"])
        sheet.append(["工时差异", f"{totals.get('hoursDelta', 0):.2f}"])
        sheet.append(["PDF总金额", f"${totals.get('pdfAmount', 0):.2f}"])
        sheet.append(["Excel总金额", f"${totals.get('excelAmount', 0):.2f}"])
        sheet.append(["金额差异", f"${totals.get('amountDelta', 0):.2f}"])
        sheet.append([])

    # 仓库问题
    warehouse_issues = metrics.get("warehouseIssues", [])
    if warehouse_issues:
        sheet.append(["仓库问题"])
        for issue in warehouse_issues:
            sheet.append(["", issue])
        sheet.append([])

    # 名称模式
    name_patterns = metrics.get("namePatterns", {})
    if name_patterns:
        sheet.append(["名称模式"])
        sheet.append(["包含中文", "是" if name_patterns.get("hasChinese") else "否"])
        sheet.append(["包含英文", "是" if name_patterns.get("hasEnglish") else "否"])
        sheet.append(["中英文混合", "是" if name_patterns.get("hasMixed") else "否"])

    _format(sheet)


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


def _write_candidate_matches(workbook: Workbook, rows: List[Dict[str, Any]]) -> None:
    headers = ["pdfEmployeeName", "excelEmployeeName", "nameSimilarity", "pdfHoursTotal", "excelHoursTotal", "hoursDelta", "pdfAmountTotal", "excelAmountTotal", "amountDelta", "recommendation", "sourceRefs"]
    sheet = workbook.create_sheet("姓名格式差异")
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
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
