"""FBU绩效核算引擎 - 数据解析"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from collections import defaultdict
import openpyxl
import msoffcrypto
import io

from .engines.base import EmployeeData, FBUPerformanceEngine
from .engines.attendance import AttendanceProcessor
from .engines.salary import SalaryProcessor
from .engines.bonus import BonusCalculator


class FBUPerformanceParser:
    """FBU绩效数据解析器"""

    def __init__(self):
        self.engine = FBUPerformanceEngine()
        self.attendance_processor = AttendanceProcessor()
        self.salary_processor = SalaryProcessor()

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

    def parse_attendance(self, filepath: str, target_month: int) -> dict:
        """解析考勤数据"""
        wb = self.load_excel(filepath)
        ws = wb['sheet1']

        # 读取数据行
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is not None:
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
            if row[0] is not None:
                rows.append(row)

        return self.salary_processor.load(rows)

    def parse_performance(self, filepath: str) -> dict:
        """解析绩效报表"""
        wb = self.load_excel(filepath)
        ws = wb[wb.sheetnames[0]]

        performance_data = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[3] is None:  # 工号列
                continue

            emp_id = str(row[3]).strip()
            score = row[16]  # 总分
            level = row[17]  # 总等级
            coefficient = row[18]  # 绩效系数

            performance_data[emp_id] = {
                'score': float(score) if score else None,
                'level': str(level) if level else None,
                'coefficient': float(coefficient) if coefficient else None,
            }

        return performance_data

    def build_employees(
        self,
        attendance_data: dict,
        salary_data: dict,
        performance_data: dict,
    ) -> list[EmployeeData]:
        """构建员工数据"""
        employees = []

        for emp_id, hours in attendance_data.items():
            # 获取薪资信息
            salary_info = salary_data.get(emp_id, {})
            hourly_rate = salary_info.get('hourly_rate', 0)
            ratio = salary_info.get('ratio', 0)

            # 获取绩效信息
            perf_info = performance_data.get(emp_id, {})

            # 判断岗位类型（简化：有得分用仓库端，否则职能端）
            score = perf_info.get('score')
            level = perf_info.get('level')
            job_type = 'warehouse' if score is not None else 'functional'

            # 处理白班
            if hours['白班']['计薪出勤'] > 0 or hours['白班']['OT1.5'] > 0:
                emp = EmployeeData(
                    employee_id=emp_id,
                    name='',  # 后续从花名册补充
                    hourly_rate=hourly_rate,
                    performance_ratio=ratio,
                    performance_score=score,
                    performance_level=level,
                    job_type=job_type,
                    base_hours=hours['白班']['计薪出勤'],
                    ot15_hours=hours['白班']['OT1.5'],
                    ot20_hours=hours['白班']['OT2.0'],
                    sick_hours=hours['白班']['病假'],
                    annual_hours=hours['白班']['年假'],
                    holiday_hours=hours['白班']['节假日'],
                    is_night_shift=False,
                )
                employees.append(emp)

            # 处理夜班
            if hours['has_night_shift'] and (hours['夜班']['计薪出勤'] > 0 or hours['夜班']['OT1.5'] > 0):
                emp = EmployeeData(
                    employee_id=f"{emp_id}-1",
                    name='',
                    hourly_rate=hourly_rate + 1,  # 夜班时薪+1
                    performance_ratio=ratio,
                    performance_score=score,
                    performance_level=level,
                    job_type=job_type,
                    base_hours=hours['夜班']['计薪出勤'],
                    ot15_hours=hours['夜班']['OT1.5'],
                    ot20_hours=hours['夜班']['OT2.0'],
                    sick_hours=hours['夜班']['病假'],
                    annual_hours=hours['夜班']['年假'],
                    holiday_hours=hours['夜班']['节假日'],
                    is_night_shift=True,
                )
                employees.append(emp)

        return employees

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
        employees = self.build_employees(attendance_data, salary_data, performance_data)

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
            if row[0] is not None:
                rows.append(row)

        # 处理考勤数据
        attendance_data = self.attendance_processor.process(rows, target_month)

        # 构建明细列表
        employee_list = []
        for emp_id, hours in attendance_data.items():
            employee_list.append({
                "employee_id": emp_id,
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
        total_base_hours = sum(e['total_base_hours'] for e in employee_list)
        total_ot15 = sum(e['total_ot15'] for e in employee_list)
        total_ot20 = sum(e['total_ot20'] for e in employee_list)

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
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
            if row[0] is not None:
                rows.append(row)

        salary_data = self.salary_processor.load(rows)

        # 构建明细列表
        employee_list = []
        for emp_id, info in salary_data.items():
            employee_list.append({
                "employee_id": emp_id,
                "hourly_rate": info.get('hourly_rate', 0),
                "ratio": info.get('ratio', 0),
            })

        # 汇总统计
        total_employees = len(employee_list)
        avg_hourly_rate = sum(e['hourly_rate'] for e in employee_list) / total_employees if total_employees > 0 else 0

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
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
            if row[3] is None:  # 工号列
                continue

            emp_id = str(row[3]).strip()
            score = row[16]  # 总分
            level = row[17]  # 总等级
            coefficient = row[18]  # 绩效系数

            employee_list.append({
                "employee_id": emp_id,
                "score": float(score) if score else None,
                "level": str(level) if level else None,
                "coefficient": float(coefficient) if coefficient else None,
            })

            if level:
                level_distribution[str(level)] += 1

        # 汇总统计
        total_employees = len(employee_list)
        avg_score = sum(e['score'] for e in employee_list if e['score']) / total_employees if total_employees > 0 else 0

        return {
            "employees": employee_list,
            "summary": {
                "total_employees": total_employees,
                "avg_score": round(avg_score, 2),
                "level_distribution": dict(level_distribution),
            }
        }

    def parse_all_from_step_data(
        self,
        attendance_data: list,
        salary_data: list,
        performance_data: list,
    ) -> FBUPerformanceEngine:
        """
        从分步数据计算最终结果

        Args:
            attendance_data: 考勤预览数据中的employees列表
            salary_data: 薪资预览数据中的employees列表
            performance_data: 绩效预览数据中的employees列表

        Returns:
            计算完成的引擎实例
        """
        # 转换为字典格式
        attendance_dict = {}
        for emp in attendance_data:
            emp_id = emp['employee_id']
            attendance_dict[emp_id] = {
                '白班': emp['day_shift'],
                '夜班': emp['night_shift'],
                'has_night_shift': emp['has_night_shift'],
            }

        salary_dict = {}
        for emp in salary_data:
            emp_id = emp['employee_id']
            salary_dict[emp_id] = {
                'hourly_rate': emp['hourly_rate'],
                'ratio': emp['ratio'],
            }

        performance_dict = {}
        for emp in performance_data:
            emp_id = emp['employee_id']
            performance_dict[emp_id] = {
                'score': emp['score'],
                'level': emp['level'],
                'coefficient': emp['coefficient'],
            }

        # 构建员工数据
        employees = self.build_employees(attendance_dict, salary_dict, performance_dict)

        # 计算绩效奖金
        for emp in employees:
            BonusCalculator.calculate(emp)
            self.engine.add_employee(emp)

        return self.engine
