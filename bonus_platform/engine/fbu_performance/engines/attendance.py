"""FBU绩效核算引擎 - 考勤数据处理"""
from __future__ import annotations
from datetime import datetime
from collections import defaultdict
from typing import Optional
from .base import EmployeeData


class AttendanceProcessor:
    """考勤数据处理器"""

    # 考勤日报表列索引映射
    COLUMN_MAP = {
        '考勤日期': 0,
        '姓名': 1,
        '工号': 2,
        '班次名称': 19,
        '班次上班时间': 21,
        '节假日时长': 46,  # AU列
        '年假时长': 47,    # AV列
        '病假时长': 48,    # AW列
        'OT1.5': 100,      # CW列
        'OT2.0': 103,      # CZ列
        '计薪出勤时长': 117,  # DN列
        '病假余额结算': 148,  # ES列
    }

    @staticmethod
    def cell(row, index: int, default=None):
        """安全读取固定列模板单元格。"""
        return row[index] if len(row) > index else default

    @staticmethod
    def number(value) -> float:
        if value is None or value == "":
            return 0.0
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return 0.0
        return float(value)

    @staticmethod
    def is_night_shift(shift_start_time) -> bool:
        """判断是否夜班：班次上班时间 >= 14:00"""
        if shift_start_time is None:
            return False

        if isinstance(shift_start_time, str):
            try:
                if ':' in shift_start_time:
                    hour = int(shift_start_time.split(':')[0])
                    return hour >= 14
            except (ValueError, IndexError):
                pass
        elif isinstance(shift_start_time, datetime):
            return shift_start_time.hour >= 14

        return False

    @staticmethod
    def parse_date(date_str) -> Optional[datetime]:
        """解析日期字符串"""
        if isinstance(date_str, datetime):
            return date_str
        if isinstance(date_str, str):
            for fmt in ['%Y/%m/%d', '%Y-%m-%d']:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        return None

    def process(self, rows: list, target_month: int) -> dict[str, dict]:
        """
        处理考勤数据，按员工汇总工时

        Args:
            rows: 考勤日报表数据行
            target_month: 目标月份

        Returns:
            员工工时汇总 {employee_id: {白班/夜班数据}}
        """
        # 筛选当月数据
        monthly_data = []
        for row in rows:
            if not row or self.cell(row, 0) is None:
                continue
            dt = self.parse_date(self.cell(row, 0))
            if dt and dt.month == target_month:
                monthly_data.append(row)

        # 按员工+班次类型汇总
        employee_hours = defaultdict(lambda: {
            '白班': {'计薪出勤': 0, 'OT1.5': 0, 'OT2.0': 0, '病假': 0, '年假': 0, '节假日': 0},
            '夜班': {'计薪出勤': 0, 'OT1.5': 0, 'OT2.0': 0, '病假': 0, '年假': 0, '节假日': 0},
            'has_night_shift': False,
        })

        for row in monthly_data:
            emp_id = str(self.cell(row, 2)).strip() if self.cell(row, 2) else None
            if not emp_id:
                continue

            # 判断夜班
            shift_start = self.cell(row, 21)
            is_night = self.is_night_shift(shift_start)
            shift_type = '夜班' if is_night else '白班'

            if is_night:
                employee_hours[emp_id]['has_night_shift'] = True

            # 累加工时
            employee_hours[emp_id][shift_type]['计薪出勤'] += self.number(self.cell(row, 117))
            employee_hours[emp_id][shift_type]['OT1.5'] += self.number(self.cell(row, 100))
            employee_hours[emp_id][shift_type]['OT2.0'] += self.number(self.cell(row, 103))
            employee_hours[emp_id][shift_type]['病假'] += self.number(self.cell(row, 48))
            employee_hours[emp_id][shift_type]['年假'] += self.number(self.cell(row, 47))
            employee_hours[emp_id][shift_type]['节假日'] += self.number(self.cell(row, 46))

        return dict(employee_hours)
