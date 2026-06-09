"""Excel export for calculation results."""
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

    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
    WARNING_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    BORDER = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin'),
    )

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
        wb = openpyxl.Workbook()

        # 1. 详情页
        ws_detail = wb.active
        ws_detail.title = "计算详情"
        self._write_detail_sheet(ws_detail, results)

        # 2. 汇总页
        ws_summary = wb.create_sheet("汇总统计")
        self._write_summary_sheet(ws_summary, attendance_month, summary, results)

        # 3. 异常页
        warnings = [r for r in results if r.get("warnings")]
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
        headers = [
            "工号", "姓名", "部门",
            "全勤奖", "餐补", "外宿补贴", "工龄奖", "合计",
            "备注"
        ]

        # 写表头
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.alignment = Alignment(horizontal='center')
            cell.border = self.BORDER

        # 写数据
        for row_idx, result in enumerate(results, 2):
            ws.cell(row=row_idx, column=1, value=result.get("employee_id", "")).border = self.BORDER
            ws.cell(row=row_idx, column=2, value=result.get("employee_name", "")).border = self.BORDER
            ws.cell(row=row_idx, column=3, value=result.get("department", "")).border = self.BORDER

            ws.cell(row=row_idx, column=4, value=result.get("quanqinjiang", 0)).border = self.BORDER
            ws.cell(row=row_idx, column=5, value=result.get("canbu", 0)).border = self.BORDER
            ws.cell(row=row_idx, column=6, value=result.get("waisu_butie", 0)).border = self.BORDER
            ws.cell(row=row_idx, column=7, value=result.get("gonglingjiang", 0)).border = self.BORDER
            ws.cell(row=row_idx, column=8, value=result.get("total", 0)).border = self.BORDER
            ws.cell(row=row_idx, column=9, value=result.get("warnings", "")).border = self.BORDER

            # 有警告的行标黄
            if result.get("warnings"):
                for col in range(1, 10):
                    ws.cell(row=row_idx, column=col).fill = self.WARNING_FILL

        # 设置列宽
        widths = [12, 10, 15, 10, 10, 10, 10, 10, 30]
        for col, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col)].width = width

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

    def _write_warnings_sheet(self, ws, warnings: List[Dict[str, Any]]):
        """Write warnings sheet."""
        headers = ["工号", "姓名", "警告信息"]

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)

        for row_idx, result in enumerate(warnings, 2):
            ws.cell(row=row_idx, column=1, value=result.get("employee_id", ""))
            ws.cell(row=row_idx, column=2, value=result.get("employee_name", ""))
            ws.cell(row=row_idx, column=3, value=result.get("warnings", ""))

        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 50

    @staticmethod
    def _count_nonzero(results: List[Dict], field: str) -> int:
        return sum(1 for r in results if r.get(field, 0) > 0)

    @staticmethod
    def _sum_field(results: List[Dict], field: str) -> float:
        return round(sum(r.get(field, 0) for r in results), 2)
