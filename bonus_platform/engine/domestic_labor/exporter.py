"""Excel export for domestic labor calculation results."""
from pathlib import Path
from typing import Any, Dict, List
from datetime import date

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
except ImportError:
    openpyxl = None


class ExcelExporter:
    """Export calculation results to Excel."""

    HEADER_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
    WARNING_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    OK_FILL = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
    BORDER = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin'),
    )
    SUBJECTS = [
        ("quanqinjiang", "全勤奖"),
        ("canbu", "餐补"),
        ("waisu_butie", "外宿补贴"),
        ("gonglingjiang", "工龄奖"),
    ]
    CANBU_HEADERS = [
        "工号", "姓名", "工作地区", "部门", "岗位", "餐补资格", "适用规则",
        "有效餐补天数", "日考勤记录数", "日餐补合计", "封顶金额", "是否触发封顶",
        "应发餐补", "计算公式", "关键输入", "中间值", "计算步骤", "异常/提示",
    ]
    GENERAL_HEADERS = [
        "工号", "姓名", "工作地区", "部门", "岗位",
        "全勤奖", "餐补", "外宿补贴", "工龄奖", "应发合计",
        "规则命中", "计算公式", "关键输入", "中间值", "计算步骤", "异常/提示",
    ]

    def __init__(self, output_path: str):
        if openpyxl is None:
            raise ImportError("openpyxl is required: pip install openpyxl")
        self.output_path = Path(output_path)

    def export(
        self,
        results: List[Dict[str, Any]],
        attendance_month: str,
        summary: Dict[str, Any] = None,
    ) -> str:
        """Export results to Excel.

        Args:
            results: List of calculation result records
            attendance_month: Attendance month (YYYYMM)
            summary: Summary statistics

        Returns:
            Output file path
        """
        cleaned_results = [result for result in results if self._has_valid_employee_id(result)]
        wb = openpyxl.Workbook()

        # 1. 详情页
        ws_detail = wb.active
        ws_detail.title = "计算详情"
        self._write_detail_sheet(ws_detail, cleaned_results)

        # 2. 汇总页
        ws_summary = wb.create_sheet("汇总统计")
        self._write_summary_sheet(ws_summary, attendance_month, summary, cleaned_results)

        # 3. 异常页
        warnings = [r for r in cleaned_results if r.get("warnings") or r.get("exceptions")]
        if warnings:
            ws_warnings = wb.create_sheet("异常记录")
            self._write_warnings_sheet(ws_warnings, warnings)

        # 保存
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(self.output_path))
        wb.close()

        return str(self.output_path)

    def _write_detail_sheet(self, ws, results: List[Dict[str, Any]]):
        """Write detail sheet."""
        if self._is_canbu_only(results):
            self._write_canbu_detail_sheet(ws, results)
            return

        headers = self.GENERAL_HEADERS

        # 写表头
        for col, header in enumerate(headers, 1):
            self._write_header_cell(ws, 1, col, header)

        # 写数据
        for row_idx, result in enumerate(results, 2):
            audit = self._first_audit(result)
            inputs = audit.get("inputs", {}) if audit else {}
            intermediate = audit.get("intermediate_values", {}) if audit else {}
            values = [
                result.get("employee_id", ""),
                result.get("employee_name", ""),
                inputs.get("工作地区", intermediate.get("工作地区", "")),
                result.get("department", ""),
                inputs.get("岗位名称", intermediate.get("岗位名称", "")),
                self._number(result.get("quanqinjiang", 0)),
                self._number(result.get("canbu", 0)),
                self._number(result.get("waisu_butie", 0)),
                self._number(result.get("gonglingjiang", 0)),
                self._number(result.get("total", 0)),
                audit.get("rule_name", "") if audit else "",
                audit.get("formula", "") if audit else "",
                self._format_mapping(inputs),
                self._format_mapping(intermediate),
                self._format_steps(audit.get("steps", []) if audit else []),
                self._format_warning(result),
            ]
            for col, value in enumerate(values, 1):
                self._write_body_cell(ws, row_idx, col, value)

            # 有警告的行标黄
            if result.get("warnings") or result.get("exceptions"):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=col).fill = self.WARNING_FILL

        # 设置列宽
        self._set_widths(ws, [14, 12, 12, 18, 14, 10, 10, 12, 10, 10, 22, 24, 38, 38, 46, 42])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    def _write_canbu_detail_sheet(self, ws, results: List[Dict[str, Any]]):
        """Write canbu detail sheet with auditable payroll fields."""
        for col, header in enumerate(self.CANBU_HEADERS, 1):
            self._write_header_cell(ws, 1, col, header)

        for row_idx, result in enumerate(results, 2):
            detail = self._subject_detail(result, "canbu")
            audit = self._subject_audit(result, "canbu")
            inputs = audit.get("inputs", {}) if audit else {}
            intermediate = audit.get("intermediate_values", {}) if audit else {}
            daily_amounts = detail.get("日餐补明细", [])
            daily_standard = self._number(intermediate.get("日标准", 19))
            raw_total = self._number(
                detail.get("月累计", intermediate.get("日餐补合计", result.get("canbu", 0)))
            )
            final_amount = self._number(result.get("canbu", detail.get("amount", 0)))
            is_capped = detail.get("是否触发封顶", intermediate.get("是否触发封顶", False))
            work_area = inputs.get("工作地区", intermediate.get("工作地区", ""))
            position = inputs.get("岗位名称", intermediate.get("岗位名称", ""))
            eligibility = "不享有/未发放" if final_amount <= 0 else "享有"
            if "岗位是否在享有名单" in intermediate:
                eligibility = "享有" if intermediate.get("岗位是否在享有名单") else "不享有/未发放"

            values = [
                result.get("employee_id", ""),
                result.get("employee_name", ""),
                work_area,
                result.get("department", ""),
                position,
                eligibility,
                detail.get("地区规则", audit.get("rule_name", "") if audit else ""),
                self._effective_days(daily_amounts, daily_standard),
                inputs.get("日考勤记录数", intermediate.get("日考勤记录数", "")),
                raw_total,
                self._number(detail.get("封顶金额", intermediate.get("月封顶", ""))),
                "是" if is_capped else "否",
                final_amount,
                audit.get("formula", "") if audit else "",
                self._format_mapping(inputs),
                self._format_mapping(intermediate),
                self._format_steps(audit.get("steps", []) if audit else []),
                self._format_warning(result),
            ]
            for col, value in enumerate(values, 1):
                self._write_body_cell(ws, row_idx, col, value)

            if result.get("warnings") or result.get("exceptions"):
                for col in range(1, len(self.CANBU_HEADERS) + 1):
                    ws.cell(row=row_idx, column=col).fill = self.WARNING_FILL
            elif final_amount <= 0:
                ws.cell(row=row_idx, column=6).fill = self.WARNING_FILL
            else:
                ws.cell(row=row_idx, column=6).fill = self.OK_FILL

        self._set_widths(ws, [14, 12, 12, 18, 14, 14, 24, 14, 14, 14, 12, 12, 12, 26, 44, 44, 52, 42])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    def _write_summary_sheet(self, ws, attendance_month: str, summary: Dict[str, Any], results: List[Dict[str, Any]]):
        """Write summary sheet."""
        ws.cell(row=1, column=1, value="AI薪酬核算汇总").font = Font(bold=True, size=14)
        ws.cell(row=2, column=1, value=f"考勤月份: {attendance_month}")
        ws.cell(row=3, column=1, value=f"生成时间: {date.today().isoformat()}")

        # 汇总统计
        row = 5
        stats = [
            ("项目", "人数", "金额"),
            ("全勤奖", self._count_nonzero(results, "quanqinjiang"), self._sum_field(results, "quanqinjiang")),
            ("餐补", self._count_nonzero(results, "canbu"), self._sum_field(results, "canbu")),
            ("外宿补贴", self._count_nonzero(results, "waisu_butie"), self._sum_field(results, "waisu_butie")),
            ("工龄奖", self._count_nonzero(results, "gonglingjiang"), self._sum_field(results, "gonglingjiang")),
            ("合计", len(results), self._sum_field(results, "total")),
        ]

        for r, data in enumerate(stats):
            for c, val in enumerate(data):
                cell = ws.cell(row=row + r, column=c + 1, value=val)
                cell.border = self.BORDER
                if r == 0:
                    cell.fill = self.HEADER_FILL
                    cell.font = self.HEADER_FONT
        self._set_widths(ws, [18, 12, 14])

    def _write_warnings_sheet(self, ws, warnings: List[Dict[str, Any]]):
        """Write warnings sheet."""
        headers = ["工号", "姓名", "异常等级", "异常科目", "异常说明", "建议动作", "原始提示"]

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)

        for row_idx, result in enumerate(warnings, 2):
            exception = self._first_exception(result)
            values = [
                result.get("employee_id", ""),
                result.get("employee_name", ""),
                exception.get("level", "") if exception else "",
                exception.get("subject", "") if exception else "",
                exception.get("message", "") if exception else "",
                exception.get("suggested_action", "") if exception else "",
                result.get("warnings", ""),
            ]
            for col, value in enumerate(values, 1):
                self._write_body_cell(ws, row_idx, col, value)

        self._set_widths(ws, [14, 12, 12, 12, 52, 44, 52])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    @staticmethod
    def _count_nonzero(results: List[Dict], field: str) -> int:
        return sum(1 for r in results if r.get(field, 0) > 0)

    @staticmethod
    def _sum_field(results: List[Dict], field: str) -> float:
        return round(sum(r.get(field, 0) for r in results), 2)

    @staticmethod
    def _has_valid_employee_id(result: Dict[str, Any]) -> bool:
        employee_id = str(result.get("employee_id", "") or "").strip()
        return employee_id.lower() not in {"", "none", "nan", "null"}

    @classmethod
    def _is_canbu_only(cls, results: List[Dict[str, Any]]) -> bool:
        if not results:
            return False
        present_subjects = {
            key
            for result in results
            for key, _label in cls.SUBJECTS
            if result.get(key, 0) or key in (result.get("subject_details") or {})
        }
        return present_subjects == {"canbu"}

    @classmethod
    def _subject_detail(cls, result: Dict[str, Any], subject: str) -> Dict[str, Any]:
        payload = (result.get("subject_details") or {}).get(subject) or {}
        details = payload.get("details") or {}
        if "amount" not in details and "amount" in payload:
            details = {**details, "amount": payload.get("amount")}
        return details

    @classmethod
    def _subject_audit(cls, result: Dict[str, Any], subject: str) -> Dict[str, Any]:
        payload = (result.get("subject_details") or {}).get(subject) or {}
        details = payload.get("details") or {}
        return payload.get("audit_explanation") or details.get("audit_explanation") or {}

    @classmethod
    def _first_audit(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        for key, _label in cls.SUBJECTS:
            audit = cls._subject_audit(result, key)
            if audit:
                return audit
        return {}

    @staticmethod
    def _first_exception(result: Dict[str, Any]) -> Dict[str, Any]:
        exceptions = result.get("exceptions") or []
        return exceptions[0] if exceptions else {}

    @staticmethod
    def _number(value: Any) -> Any:
        if value in ("", None):
            return ""
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return value

    @classmethod
    def _effective_days(cls, daily_amounts: Any, daily_standard: Any) -> Any:
        if not isinstance(daily_amounts, list):
            return ""
        standard = cls._number(daily_standard)
        if not isinstance(standard, (int, float)) or standard <= 0:
            return ""
        return round(sum(cls._number(item) or 0 for item in daily_amounts) / standard, 2)

    @classmethod
    def _format_mapping(cls, mapping: Dict[str, Any]) -> str:
        if not mapping:
            return ""
        parts = []
        for key, value in mapping.items():
            if isinstance(value, list):
                text = f"{key}: {len(value)}项"
            else:
                text = f"{key}: {cls._format_value(value)}"
            parts.append(text)
        return "\n".join(parts)

    @classmethod
    def _format_value(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, float):
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _format_steps(steps: List[Any]) -> str:
        if not steps:
            return ""
        return "\n".join(f"{idx}. {step}" for idx, step in enumerate(steps, 1))

    @staticmethod
    def _format_warning(result: Dict[str, Any]) -> str:
        pieces = []
        if result.get("warnings"):
            pieces.append(str(result.get("warnings")))
        for exception in result.get("exceptions") or []:
            message = exception.get("message") if isinstance(exception, dict) else str(exception)
            if message:
                pieces.append(message)
        return "\n".join(pieces)

    def _write_header_cell(self, ws, row: int, col: int, value: Any) -> None:
        cell = ws.cell(row=row, column=col, value=value)
        cell.fill = self.HEADER_FILL
        cell.font = self.HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = self.BORDER

    def _write_body_cell(self, ws, row: int, col: int, value: Any) -> None:
        cell = ws.cell(row=row, column=col, value=value)
        cell.border = self.BORDER
        cell.alignment = Alignment(vertical='top', wrap_text=True)

    @staticmethod
    def _set_widths(ws, widths: List[int]) -> None:
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width
