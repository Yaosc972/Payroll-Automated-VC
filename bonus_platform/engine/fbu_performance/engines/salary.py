"""FBU绩效核算引擎 - 薪资数据处理"""
from __future__ import annotations
from typing import Optional


class SalaryProcessor:
    """薪资数据处理器"""

    # 薪资档案列索引映射
    COLUMN_MAP = {
        '姓名': 0,
        '工号': 1,
        '时薪标准': 11,
        '绩效比例': 9,  # 月度绩效奖金比例(%)
    }

    def __init__(self):
        self.salary_data: dict[str, dict] = {}

    def load(self, rows: list) -> dict[str, dict]:
        """
        加载薪资档案数据

        Args:
            rows: 薪资档案数据行

        Returns:
            薪资数据 {employee_id: {hourly_rate, ratio}}
        """
        self.salary_data = {}

        for row in rows:
            if not row or row[1] is None:
                continue

            emp_id = str(row[1]).strip()
            hourly_rate = row[11]  # 时薪标准
            ratio = row[9]        # 绩效比例

            if emp_id and hourly_rate:
                # 绩效比例可能是百分比形式，需要转换
                if ratio and ratio > 1:
                    ratio = ratio / 100

                self.salary_data[emp_id] = {
                    'hourly_rate': float(hourly_rate),
                    'ratio': float(ratio) if ratio else 0.0,
                }

        return self.salary_data

    def get_hourly_rate(self, employee_id: str, is_night_shift: bool = False) -> float:
        """获取时薪（夜班+1）"""
        base_rate = self.salary_data.get(employee_id, {}).get('hourly_rate', 0)
        return base_rate + 1 if is_night_shift else base_rate

    def get_ratio(self, employee_id: str) -> float:
        """获取绩效比例"""
        return self.salary_data.get(employee_id, {}).get('ratio', 0.0)
