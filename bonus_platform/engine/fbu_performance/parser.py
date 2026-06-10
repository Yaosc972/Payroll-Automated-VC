"""FBU绩效核算引擎 - 数据解析"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from collections import defaultdict
import openpyxl
import msoffcrypto
import io
import xlrd

from .engines.base import CalculationSegment, EmployeeData, FBUPerformanceEngine
from .engines.attendance import AttendanceProcessor
from .engines.salary import SalaryProcessor
from .engines.bonus import BonusCalculator


def _cell(row, index: int, default=None):
    if index is None:
        return default
    return row[index] if len(row) > index else default


def _to_float(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "")
        if not cleaned:
            return default
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1].strip()
            return float(cleaned) / 100
        return float(cleaned)
    return float(value)


def _find_column(headers, names: list[str], fallback: int | None = None) -> int | None:
    normalized = {
        str(header).strip(): index
        for index, header in enumerate(headers)
        if header is not None and str(header).strip()
    }
    for name in names:
        if name in normalized:
            return normalized[name]
    return fallback


DISTRICT_MANAGER_IDS = {"zt15638"}
FUNCTIONAL_DEPARTMENT_KEYWORDS = (
    "FBU HRBP Dept.",
    "渠道管理部",
    "新泽西区行政部",
)


def classify_job_type(employee_id: str, department: str) -> str:
    """按FBU美洲业务口径区分仓库端、职能端和区长。"""
    normalized_id = str(employee_id or "").strip().lower()
    if normalized_id in DISTRICT_MANAGER_IDS:
        return "district_manager"
    if any(keyword in (department or "") for keyword in FUNCTIONAL_DEPARTMENT_KEYWORDS):
        return "functional"
    return "warehouse"


class FBUPerformanceParser:
    """FBU绩效数据解析器"""

    def __init__(self):
        self.engine = FBUPerformanceEngine()
        self.attendance_processor = AttendanceProcessor()
        self.salary_processor = SalaryProcessor()
        self.employee_roster = {}  # 花名册数据 {emp_id: {name, department, ...}}

    @staticmethod
    def load_excel(filepath: str, password: Optional[str] = None) -> openpyxl.Workbook:
        """加载Excel文件（支持密码保护）"""
        if password:
            with open(filepath, "rb") as f:
                ms_file = msoffcrypto.OfficeFile(f)
                ms_file.load_key(password=password)
                decrypted = io.BytesIO()
                ms_file.decrypt(decrypted)
                decrypted.seek(0)
                return openpyxl.load_workbook(decrypted, data_only=True)
        else:
            return openpyxl.load_workbook(filepath, data_only=True)

    def load_roster(self, filepath: str) -> dict:
        """
        加载花名册数据

        Args:
            filepath: 花名册文件路径

        Returns:
            员工信息字典 {emp_id: {name, department, job_type, ...}}
        """
        path = Path(filepath)
        if path.suffix.lower() == ".xls":
            book = xlrd.open_workbook(filepath)
            sheet = book.sheet_by_index(0)
            headers = sheet.row_values(0) if sheet.nrows else []
            rows = (
                sheet.row_values(row_idx)
                for row_idx in range(1, sheet.nrows)
            )
        else:
            wb = self.load_excel(filepath)
            ws = wb[wb.sheetnames[0]]
            headers = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), [])
            rows = ws.iter_rows(min_row=2, values_only=True)

        # 找到关键列的索引
        col_map = {
            '姓名': _find_column(headers, ['姓名'], 0),
            '工号': _find_column(headers, ['工号'], 3),
            '二级部门': _find_column(headers, ['二级部门'], 19),
            '三级部门': _find_column(headers, ['三级部门'], 20),
            '四级部门': _find_column(headers, ['四级部门'], 21),
            '五级部门': _find_column(headers, ['五级部门'], 22),
            '六级部门': _find_column(headers, ['六级部门'], 23),
            '七级部门': _find_column(headers, ['七级部门'], 24),
            '八级部门': _find_column(headers, ['八级部门'], 25),
            '划分区域': _find_column(headers, ['划分区域'], 89),
            '领色': _find_column(headers, ['领色'], 107),
        }

        roster = {}
        for row in rows:
            if not row or _cell(row, col_map['工号']) is None:
                continue

            emp_id = str(_cell(row, col_map['工号'])).strip()
            name = str(_cell(row, col_map['姓名'])).strip() if _cell(row, col_map['姓名']) else ''

            # 构建部门全称：二级-三级-四级-五级-六级-七级-八级
            dept_parts = []
            for level in ['二级部门', '三级部门', '四级部门', '五级部门', '六级部门', '七级部门', '八级部门']:
                val = _cell(row, col_map[level])
                if val and str(val).strip():
                    dept_parts.append(str(val).strip())
            department_full = '-'.join(dept_parts) if dept_parts else ''

            # 划分区域
            area = str(_cell(row, col_map['划分区域'])).strip() if _cell(row, col_map['划分区域']) else ''

            job_type = classify_job_type(emp_id, department_full)

            roster[emp_id] = {
                'name': name,
                'department': department_full,
                'area': area,
                'job_type': job_type,
            }

        self.employee_roster = roster
        return roster

    def get_employee_info(self, emp_id: str) -> dict:
        """获取员工信息"""
        return self.employee_roster.get(emp_id, {
            'name': '',
            'department': '',
            'area': '',
            'job_type': 'warehouse',
        })

    def parse_attendance(self, filepath: str, target_month: int) -> dict:
        """解析考勤数据"""
        wb = self.load_excel(filepath)
        ws = wb['sheet1']

        # 读取数据行
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 0) is not None:
                rows.append(row)

        # 处理考勤数据
        return self.attendance_processor.process(rows, target_month)

    def parse_salary(self, filepath: str) -> dict:
        """解析薪资档案"""
        wb = self.load_excel(filepath)
        ws = wb[wb.sheetnames[0]]

        # 读取数据行
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 0) is not None:
                rows.append(row)

        return self.salary_processor.load(rows)

    def parse_performance(self, filepath: str) -> dict:
        """解析绩效报表"""
        wb = self.load_excel(filepath)
        ws = wb[wb.sheetnames[0]]

        performance_data = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 3) is None:  # 工号列
                continue

            emp_id = str(_cell(row, 3)).strip()
            score = _cell(row, 16)  # 总分
            level = _cell(row, 17)  # 总等级
            coefficient = _cell(row, 18)  # 绩效系数

            performance_data[emp_id] = {
                'score': _to_float(score),
                'level': str(level).strip() if level else None,
                'coefficient': _to_float(coefficient),
            }

        return performance_data

    def build_employees(
        self,
        attendance_data: dict,
        salary_data: dict,
        performance_data: dict,
        employee_info: dict = None,
        adjustment_data: dict = None,
    ) -> list[EmployeeData]:
        """构建员工数据"""
        if employee_info is None:
            employee_info = {}
        if adjustment_data is None:
            adjustment_data = {}

        employees = []

        for emp_id, hours in attendance_data.items():
            # 获取薪资信息
            salary_info = salary_data.get(emp_id, {})
            exceptions = []
            if not salary_info:
                exceptions.append("未匹配薪资档案")
            hourly_rate = salary_info.get('hourly_rate', 0)
            ratio = salary_info.get('ratio', 0)
            fixed_performance_base = salary_info.get('fixed_performance_base', 0)

            # 获取绩效信息
            perf_info = performance_data.get(emp_id, {})
            if not perf_info:
                exceptions.append("未匹配绩效报表")

            # 获取员工信息
            info = employee_info.get(emp_id, {})
            name = info.get('name', '') or hours.get('name', '')
            department = info.get('department', '')
            area = info.get('area', '')

            # 判断岗位类型（简化：有得分用仓库端，否则职能端）
            score = perf_info.get('score')
            level = perf_info.get('level')
            uploaded_coefficient = perf_info.get('coefficient')
            job_type = info.get('job_type', 'warehouse') if info else 'warehouse'
            adjustment_segments = self._build_calculation_segments(
                adjustment_data.get(emp_id, []),
                ratio=ratio,
                coefficient=uploaded_coefficient,
            )
            if adjustment_segments and "未匹配绩效报表" in exceptions:
                exceptions.remove("未匹配绩效报表")

            # 处理白班
            if hours['白班']['计薪出勤'] > 0 or hours['白班']['OT1.5'] > 0:
                emp = EmployeeData(
                    employee_id=emp_id,
                    source_employee_id=emp_id,
                    name=name,
                    department=department,
                    area=area,
                    hourly_rate=hourly_rate,
                    performance_ratio=ratio,
                    performance_score=score,
                    performance_level=level,
                    uploaded_coefficient=uploaded_coefficient,
                    job_type=job_type,
                    fixed_performance_base=fixed_performance_base,
                    base_hours=hours['白班']['计薪出勤'],
                    ot15_hours=hours['白班']['OT1.5'],
                    ot20_hours=hours['白班']['OT2.0'],
                    sick_hours=hours['白班']['病假'],
                    annual_hours=hours['白班']['年假'],
                    holiday_hours=hours['白班']['节假日'],
                    is_night_shift=False,
                    calculation_segments=list(adjustment_segments),
                    exceptions=list(exceptions),
                )
                employees.append(emp)

            # 处理夜班
            if hours['has_night_shift'] and (hours['夜班']['计薪出勤'] > 0 or hours['夜班']['OT1.5'] > 0):
                emp = EmployeeData(
                    employee_id=f"{emp_id}-1",
                    source_employee_id=emp_id,
                    name=name,
                    department=department,
                    area=area,
                    hourly_rate=hourly_rate + 1,  # 夜班时薪+1
                    performance_ratio=ratio,
                    performance_score=score,
                    performance_level=level,
                    uploaded_coefficient=uploaded_coefficient,
                    job_type=job_type,
                    fixed_performance_base=fixed_performance_base,
                    base_hours=hours['夜班']['计薪出勤'],
                    ot15_hours=hours['夜班']['OT1.5'],
                    ot20_hours=hours['夜班']['OT2.0'],
                    sick_hours=hours['夜班']['病假'],
                    annual_hours=hours['夜班']['年假'],
                    holiday_hours=hours['夜班']['节假日'],
                    is_night_shift=True,
                    calculation_segments=list(adjustment_segments),
                    exceptions=list(exceptions),
                )
                employees.append(emp)

        return employees

    @staticmethod
    def _build_calculation_segments(
        raw_segments: list[dict],
        ratio: float,
        coefficient: float | None,
    ) -> list[CalculationSegment]:
        """把调薪拆分预览数据转成核算段。"""
        segments = []
        effective_coefficient = coefficient if coefficient is not None else 1.0
        for raw in raw_segments:
            reason = str(raw.get("reason", "")).strip()
            segment_ratio = 0.0 if "前" in reason else ratio
            segments.append(
                CalculationSegment(
                    period=str(raw.get("period", "")).strip(),
                    reason=reason,
                    performance_base=_to_float(raw.get("performance_base"), 0) or 0.0,
                    performance_ratio=segment_ratio,
                    performance_coefficient=effective_coefficient,
                )
            )
        return segments

    def parse_all(
        self,
        attendance_file: str,
        salary_file: str,
        performance_file: str,
        target_month: int,
    ) -> FBUPerformanceEngine:
        """
        解析所有数据并计算

        Args:
            attendance_file: 考勤日报表路径
            salary_file: 薪资档案路径
            performance_file: 绩效报表路径
            target_month: 目标月份

        Returns:
            计算完成的引擎实例
        """
        # 1. 解析考勤数据
        attendance_data = self.parse_attendance(attendance_file, target_month)

        # 2. 解析薪资档案
        salary_data = self.parse_salary(salary_file)

        # 3. 解析绩效报表
        performance_data = self.parse_performance(performance_file)

        # 4. 构建员工数据
        employees = self.build_employees(attendance_data, salary_data, performance_data, self.employee_roster)

        # 5. 计算绩效奖金
        for emp in employees:
            BonusCalculator.calculate(emp)
            self.engine.add_employee(emp)

        return self.engine

    def parse_attendance_preview(self, filepath: str, target_month: int) -> dict:
        """
        解析考勤数据并返回预览

        Args:
            filepath: 考勤日报表路径
            target_month: 目标月份

        Returns:
            预览数据 {员工明细列表, 汇总统计}
        """
        wb = self.load_excel(filepath)
        ws = wb['sheet1']

        # 读取数据行
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 0) is not None:
                rows.append(row)

        # 处理考勤数据
        attendance_data = self.attendance_processor.process(rows, target_month)

        # 构建明细列表
        employee_list = []
        for emp_id, hours in attendance_data.items():
            # 获取员工信息
            emp_info = self.get_employee_info(emp_id)
            roster_matched = bool(emp_info.get('name') or emp_info.get('department') or emp_info.get('area'))

            employee_list.append({
                "employee_id": emp_id,
                "name": emp_info['name'] or hours.get('name', ''),
                "department": emp_info['department'],
                "area": emp_info['area'],
                "job_type": emp_info['job_type'],
                "roster_matched": roster_matched,
                "has_night_shift": hours['has_night_shift'],
                "day_shift": hours['白班'],
                "night_shift": hours['夜班'],
                "total_base_hours": hours['白班']['计薪出勤'] + hours['夜班']['计薪出勤'],
                "total_ot15": hours['白班']['OT1.5'] + hours['夜班']['OT1.5'],
                "total_ot20": hours['白班']['OT2.0'] + hours['夜班']['OT2.0'],
            })

        # 汇总统计
        total_employees = len(employee_list)
        night_shift_count = sum(1 for e in employee_list if e['has_night_shift'])
        roster_matched = sum(1 for e in employee_list if e.get('roster_matched'))
        total_base_hours = sum(e['total_base_hours'] for e in employee_list)
        total_ot15 = sum(e['total_ot15'] for e in employee_list)
        total_ot20 = sum(e['total_ot20'] for e in employee_list)

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
                "roster_matched": roster_matched,
                "roster_missing": total_employees - roster_matched,
                "day_shift_count": total_employees - night_shift_count,
                "night_shift_count": night_shift_count,
                "total_base_hours": round(total_base_hours, 2),
                "total_ot15": round(total_ot15, 2),
                "total_ot20": round(total_ot20, 2),
            }
        }

    def parse_salary_preview(self, filepath: str) -> dict:
        """
        解析薪资档案并返回预览

        Args:
            filepath: 薪资档案路径

        Returns:
            预览数据 {员工明细列表, 汇总统计}
        """
        wb = self.load_excel(filepath)
        ws = wb[wb.sheetnames[0]]

        # 读取数据行
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 0) is not None:
                rows.append(row)

        salary_data = self.salary_processor.load(rows)

        # 构建明细列表
        employee_list = []
        for emp_id, info in salary_data.items():
            # 获取员工信息
            emp_info = self.get_employee_info(emp_id)

            employee_list.append({
                "employee_id": emp_id,
                "name": emp_info['name'],
                "department": emp_info['department'],
                "area": emp_info['area'],
                "hourly_rate": info.get('hourly_rate', 0),
                "ratio": info.get('ratio', 0),
                "calculation_method": info.get('calculation_method', ''),
                "fixed_performance_base": info.get('fixed_performance_base', 0),
            })

        # 汇总统计：薪资档案常包含离职或未维护时薪的员工，预览中拆开显示。
        total_employees = len(employee_list)
        valid_hourly_count = sum(1 for e in employee_list if e['hourly_rate'] > 0)
        zero_hourly_count = sum(1 for e in employee_list if e['hourly_rate'] == 0)
        avg_hourly_rate = (
            sum(e['hourly_rate'] for e in employee_list if e['hourly_rate'] > 0) / valid_hourly_count
            if valid_hourly_count > 0
            else 0
        )

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
                "valid_hourly_count": valid_hourly_count,
                "zero_hourly_count": zero_hourly_count,
                "avg_hourly_rate": round(avg_hourly_rate, 2),
            }
        }

    def parse_performance_preview(self, filepath: str) -> dict:
        """
        解析绩效报表并返回预览

        Args:
            filepath: 绩效报表路径

        Returns:
            预览数据 {员工明细列表, 汇总统计}
        """
        wb = self.load_excel(filepath)
        ws = wb[wb.sheetnames[0]]

        employee_list = []
        level_distribution = defaultdict(int)

        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, 3) is None:  # 工号列
                continue

            emp_id = str(_cell(row, 3)).strip()
            score = _cell(row, 16)  # 总分
            level = _cell(row, 17)  # 总等级
            coefficient = _cell(row, 18)  # 绩效系数

            # 获取员工信息
            emp_info = self.get_employee_info(emp_id)

            employee_list.append({
                "employee_id": emp_id,
                "name": emp_info['name'],
                "department": emp_info['department'],
                "area": emp_info['area'],
                "job_type": emp_info['job_type'],
                "score": _to_float(score),
                "level": str(level).strip() if level else None,
                "coefficient": _to_float(coefficient),
            })

            if level:
                level_distribution[str(level)] += 1

        # 汇总统计
        total_employees = len(employee_list)
        scored_employees = [e for e in employee_list if e['score'] is not None]
        avg_score = (
            sum(e['score'] for e in scored_employees) / len(scored_employees)
            if scored_employees else 0
        )

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
                "scored_employees": len(scored_employees),
                "avg_score": round(avg_score, 2),
                "level_distribution": dict(level_distribution),
            }
        }

    def parse_adjustments_preview(self, filepath: str) -> dict:
        """
        解析调薪/转正拆分表并返回预览。

        支持两种格式：
        1. 平台标准模板：按表头读取“工号/姓名/分段期间/分段绩效基数/核算标识”。
        2. 线下《仓库管理绩效基数》中的“调薪拆分”sheet固定列。
        """
        wb = self.load_excel(filepath)
        if "调薪拆分" not in wb.sheetnames:
            raise ValueError("未找到“调薪拆分”工作表")

        ws = wb["调薪拆分"]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("调薪拆分工作表为空")

        headers = rows[0]
        template_map = {
            "employee_id": _find_column(headers, ["工号", "员工工号", "employee_id"]),
            "name": _find_column(headers, ["姓名", "员工姓名", "name"]),
            "period": _find_column(headers, ["分段期间", "期间", "核算期间", "period"]),
            "performance_base": _find_column(headers, ["分段绩效基数", "绩效基数", "分段基数", "performance_base"]),
            "reason": _find_column(headers, ["核算标识", "调薪标识", "拆分标识", "reason"]),
        }
        use_template = all(template_map[key] is not None for key in ("employee_id", "period", "performance_base", "reason"))
        grouped: dict[str, dict] = {}

        for row in rows[1:]:
            if use_template:
                emp_id = str(_cell(row, template_map["employee_id"]) or "").strip()
                name = str(_cell(row, template_map["name"]) or "").strip()
                period = str(_cell(row, template_map["period"]) or "").strip()
                amount = _to_float(_cell(row, template_map["performance_base"]), 0)
                reason = str(_cell(row, template_map["reason"]) or "").strip()
            else:
                emp_id = str(_cell(row, 3) or "").strip()
                name = str(_cell(row, 4) or "").strip()
                period = str(_cell(row, 9) or "").strip()
                amount = _to_float(_cell(row, 28), 0)
                reason = str(_cell(row, 31) or "").strip()

            if not emp_id or not emp_id.lower().startswith("zt"):
                continue

            if amount is None or not reason:
                continue

            emp_info = self.get_employee_info(emp_id)
            entry = grouped.setdefault(
                emp_id,
                {
                    "employee_id": emp_id,
                    "name": emp_info["name"] or name,
                    "department": emp_info["department"],
                    "area": emp_info["area"],
                    "segments": [],
                },
            )
            entry["segments"].append({
                "period": period,
                "reason": reason,
                "performance_base": round(amount, 2),
            })

        employees = list(grouped.values())
        total_segments = sum(len(emp["segments"]) for emp in employees)
        active_base = sum(
            segment["performance_base"]
            for emp in employees
            for segment in emp["segments"]
            if "前" not in segment["reason"]
        )

        return {
            "employees": employees,
            "summary": {
                "total_employees": len(employees),
                "total_segments": total_segments,
                "active_performance_base": round(active_base, 2),
            },
        }

    def parse_all_from_step_data(
        self,
        attendance_data: list,
        salary_data: list,
        performance_data: list,
        adjustment_data: list = None,
    ) -> FBUPerformanceEngine:
        """
        从分步数据计算最终结果

        Args:
            attendance_data: 考勤预览数据中的employees列表
            salary_data: 薪资预览数据中的employees列表
            performance_data: 绩效预览数据中的employees列表
            adjustment_data: 调薪拆分预览数据中的employees列表

        Returns:
            计算完成的引擎实例
        """
        # 转换为字典格式，并保存员工信息
        employee_info = {}  # 保存员工基本信息
        attendance_dict = {}
        for emp in attendance_data:
            emp_id = emp['employee_id']
            attendance_dict[emp_id] = {
                'name': emp.get('name', ''),
                '白班': emp['day_shift'],
                '夜班': emp['night_shift'],
                'has_night_shift': emp['has_night_shift'],
            }
            # 保存员工信息
            employee_info[emp_id] = {
                'name': emp.get('name', ''),
                'department': emp.get('department', ''),
                'area': emp.get('area', ''),
                'job_type': emp.get('job_type', 'warehouse'),
            }

        salary_dict = {}
        for emp in salary_data:
            emp_id = emp['employee_id']
            salary_dict[emp_id] = {
                'hourly_rate': emp['hourly_rate'],
                'ratio': emp['ratio'],
                'calculation_method': emp.get('calculation_method', ''),
                'fixed_performance_base': emp.get('fixed_performance_base', 0),
            }

        performance_dict = {}
        for emp in performance_data:
            emp_id = emp['employee_id']
            performance_dict[emp_id] = {
                'score': emp['score'],
                'level': emp['level'],
                'coefficient': emp['coefficient'],
            }

        adjustment_dict = {}
        for emp in adjustment_data or []:
            emp_id = emp['employee_id']
            adjustment_dict[emp_id] = emp.get('segments', [])

        # 构建员工数据
        employees = self.build_employees(
            attendance_dict,
            salary_dict,
            performance_dict,
            employee_info,
            adjustment_dict,
        )

        # 计算绩效奖金
        for emp in employees:
            BonusCalculator.calculate(emp)
            self.engine.add_employee(emp)

        return self.engine
