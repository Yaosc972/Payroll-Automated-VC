"""FBU绩效核算引擎 - 考勤数据处理"""
from __future__ import annotations
from datetime import datetime
from collections import defaultdict
from typing import Optional
import re
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
        '节假日名称': 28,
        '节假日时长': 46,  # AU列
        '年假时长': 47,    # AV列
        '病假时长': 48,    # AW列
        'OT1.5': 100,      # CW列
        'OT2.0': 103,      # CZ列
        '计薪出勤时长': 117,  # DN列
        '病假余额结算': 148,  # ES列
        '标准工作时间': 51,
    }

    COLUMN_ALIASES = {
        '考勤日期': ['考勤日期'],
        '姓名': ['姓名'],
        '工号': ['工号', '员工工号'],
        '班次名称': ['班次名称'],
        '班次上班时间': ['班次上班时间'],
        '节假日名称': ['节假日名称'],
        '节假日时长': ['节假日时长'],
        '年假时长': ['年假时长'],
        '病假时长': ['病假时长'],
        'OT1.5': ['OT1.5'],
        'OT2.0': ['OT2.0'],
        '计薪出勤时长': ['计薪出勤时长'],
        '病假余额结算': ['病假余额结算（离职结算）', '病假余额结算'],
        '应出勤时长': ['应出勤时长'],
        '出勤时长': ['出勤时长'],
        '缺勤时长': ['缺勤时长'],
        '工作时长': ['工作时长'],
        '标准工作时间': ['标准工作时间'],
    }

    @staticmethod
    def cell(row, index: int, default=None):
        """安全读取固定列模板单元格。"""
        if index is None:
            return default
        return row[index] if len(row) > index else default

    @staticmethod
    def number(value) -> float:
        if value is None or value == "":
            return 0.0
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def column_map_from_headers(cls, headers: list | tuple | None) -> dict[str, int]:
        if not headers:
            return dict(cls.COLUMN_MAP)
        normalized_headers = {
            str(header).strip(): index
            for index, header in enumerate(headers)
            if header is not None and str(header).strip()
        }
        recognized_count = sum(
            1
            for aliases in cls.COLUMN_ALIASES.values()
            if any(alias in normalized_headers for alias in aliases)
        )
        if recognized_count == 0:
            return dict(cls.COLUMN_MAP)

        column_map = {}
        for key, aliases in cls.COLUMN_ALIASES.items():
            fallback = cls.COLUMN_MAP.get(key)
            column_map[key] = None
            for alias in aliases:
                if alias in normalized_headers:
                    column_map[key] = normalized_headers[alias]
                    break
            else:
                if (
                    fallback is not None
                    and fallback < len(headers)
                    and str(headers[fallback] or "").strip() in aliases
                ):
                    column_map[key] = fallback
        return column_map

    @staticmethod
    def _hour_from_text(text: str) -> int | None:
        match = re.search(r"(\d{1,2}):(\d{2})", str(text or ""))
        if not match:
            return None
        hour = int(match.group(1))
        return hour if 0 <= hour <= 23 else None

    @classmethod
    def is_night_shift(cls, shift_start_time, shift_name: str = "") -> bool:
        """判断是否夜班：班次开始于14:00后或跨午夜至05:00前。"""
        def is_night_hour(hour: int) -> bool:
            return hour >= 14 or hour < 5

        if isinstance(shift_start_time, str):
            hour = cls._hour_from_text(shift_start_time)
            if hour is not None:
                return is_night_hour(hour)
        elif isinstance(shift_start_time, datetime):
            return is_night_hour(shift_start_time.hour)

        name = str(shift_name or "").strip()
        if "夜班" in name or "晚班" in name:
            return True
        hour = cls._hour_from_text(name)
        if hour is not None:
            return is_night_hour(hour)
        return False

    @staticmethod
    def _is_holiday_shift(shift_name: str, holiday_name: str) -> bool:
        text = f"{shift_name or ''} {holiday_name or ''}".strip()
        if not text or "公休日" in text:
            return False
        return "假期" in text or "节假日" in text or "holiday" in text.lower()

    @classmethod
    def _infer_holiday_hours(
        cls,
        holiday_hours: float,
        *,
        shift_name: str,
        holiday_name: str,
        scheduled_hours: float,
        standard_work_time: float,
    ) -> float:
        if holiday_hours > 0 or not cls._is_holiday_shift(shift_name, holiday_name):
            return holiday_hours
        if scheduled_hours > 0:
            return scheduled_hours
        if standard_work_time > 0:
            return round(standard_work_time / 5, 2)
        return 8.0

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

    def process(self, rows: list, target_month: int, headers: list | tuple | None = None) -> dict[str, dict]:
        """
        处理考勤数据，按员工汇总工时

        Args:
            rows: 考勤日报表数据行
            target_month: 目标月份

        Returns:
            员工工时汇总 {employee_id: {白班/夜班数据}}
        """
        column_map = self.column_map_from_headers(headers)

        # 按员工+班次类型汇总
        employee_hours = defaultdict(lambda: {
            'name': '',
            '白班': {'计薪出勤': 0, 'OT1.5': 0, 'OT2.0': 0, '病假': 0, '病假清算': 0, '年假': 0, '节假日': 0},
            '夜班': {'计薪出勤': 0, 'OT1.5': 0, 'OT2.0': 0, '病假': 0, '病假清算': 0, '年假': 0, '节假日': 0},
            'daily_rows': [],
            '白班_daily_rows': [],
            '夜班_daily_rows': [],
            'has_night_shift': False,
            'has_target_month_rows': False,
        })

        for row in rows:
            if not row or self.cell(row, column_map['考勤日期']) is None:
                continue
            emp_id = str(self.cell(row, column_map['工号'])).strip() if self.cell(row, column_map['工号']) else None
            if not emp_id:
                continue
            dt = self.parse_date(self.cell(row, column_map['考勤日期']))
            if not dt:
                continue
            is_target_month = dt.month == target_month
            if not employee_hours[emp_id]['name'] and self.cell(row, column_map['姓名']):
                employee_hours[emp_id]['name'] = str(self.cell(row, column_map['姓名'])).strip()

            # 判断夜班
            shift_start = self.cell(row, column_map['班次上班时间'])
            shift_name = str(self.cell(row, column_map['班次名称']) or "").strip()
            is_night = self.is_night_shift(shift_start, shift_name)
            shift_type = '夜班' if is_night else '白班'

            if is_night:
                employee_hours[emp_id]['has_night_shift'] = True
            if is_target_month:
                employee_hours[emp_id]['has_target_month_rows'] = True

            base_hours = self.number(self.cell(row, column_map['计薪出勤时长']))
            ot15_hours = self.number(self.cell(row, column_map['OT1.5']))
            ot20_hours = self.number(self.cell(row, column_map['OT2.0']))
            sick_hours = self.number(self.cell(row, column_map['病假时长']))
            sick_settlement_hours = self.number(self.cell(row, column_map['病假余额结算']))
            annual_hours = self.number(self.cell(row, column_map['年假时长']))
            holiday_name = str(self.cell(row, column_map.get('节假日名称')) or "").strip()
            standard_work_time = self.number(self.cell(row, column_map.get('标准工作时间')))
            holiday_hours = self.number(self.cell(row, column_map['节假日时长']))
            scheduled_hours = self.number(self.cell(row, column_map.get('应出勤时长', 23)))
            attendance_hours = self.number(self.cell(row, column_map.get('出勤时长', 24)))
            absent_hours = self.number(self.cell(row, column_map.get('缺勤时长', 25)))
            work_hours = self.number(self.cell(row, column_map.get('工作时长', 37)))
            holiday_hours = self._infer_holiday_hours(
                holiday_hours,
                shift_name=shift_name,
                holiday_name=holiday_name,
                scheduled_hours=scheduled_hours,
                standard_work_time=standard_work_time,
            )

            # 只把核算月计入普通汇总；非核算月行仅保留给96工时制跨周期审计/计算。
            if is_target_month:
                employee_hours[emp_id][shift_type]['计薪出勤'] += base_hours
                employee_hours[emp_id][shift_type]['OT1.5'] += ot15_hours
                employee_hours[emp_id][shift_type]['OT2.0'] += ot20_hours
                employee_hours[emp_id][shift_type]['病假'] += sick_hours
                employee_hours[emp_id][shift_type]['病假清算'] += sick_settlement_hours
                employee_hours[emp_id][shift_type]['年假'] += annual_hours
                employee_hours[emp_id][shift_type]['节假日'] += holiday_hours
            daily_row = {
                "date": dt.date().isoformat(),
                "shift_type": shift_type,
                "base_hours": base_hours,
                "ot15_hours": ot15_hours,
                "ot20_hours": ot20_hours,
                "sick_hours": sick_hours,
                "sick_settlement_hours": sick_settlement_hours,
                "annual_hours": annual_hours,
                "holiday_hours": holiday_hours,
                "scheduled_hours": scheduled_hours,
                "attendance_hours": attendance_hours,
                "absent_hours": absent_hours,
                "work_hours": work_hours,
                "shift_name": shift_name,
                "shift_start_time": shift_start,
                "holiday_name": holiday_name,
                "standard_work_time": standard_work_time,
            }
            employee_hours[emp_id]['daily_rows'].append(daily_row)
            employee_hours[emp_id][f'{shift_type}_daily_rows'].append(daily_row)

        return {
            emp_id: data
            for emp_id, data in employee_hours.items()
            if data.get('has_target_month_rows')
        }
