"""FBU绩效核算引擎 - 薪资数据处理"""
from __future__ import annotations


class SalaryProcessor:
    """薪资数据处理器"""

    # 薪资档案列索引映射
    COLUMN_MAP = {
        '姓名': 0,
        '工号': 1,
        '人员状态': 2,
        '划分区域': 3,
        '成本归属': 4,
        '绩效奖金计算方式': 7,
        '月度绩效奖金基数': 8,
        '时薪标准': 11,
        '绩效比例': 9,  # 月度绩效奖金比例(%)
        '二级部门': 26,
        '三级部门': 27,
        '四级部门': 28,
        '五级部门': 29,
        '六级部门': 30,
        '七级部门': 31,
        '八级部门': 32,
        '岗位': 33,
    }

    COLUMN_ALIASES = {
        '姓名': ['姓名'],
        '工号': ['工号', '员工工号'],
        '人员状态': ['人员状态'],
        '划分区域': ['划分区域'],
        '成本归属': ['成本归属'],
        '绩效奖金计算方式': ['绩效奖金计算方式'],
        '月度绩效奖金基数': ['月度绩效奖金基数'],
        '时薪标准': ['时薪标准', '基本工资标准'],
        '绩效比例': ['月度绩效奖金比例(%)', '月度绩效奖金比例', '绩效比例'],
        '二级部门': ['二级部门'],
        '三级部门': ['三级部门'],
        '四级部门': ['四级部门'],
        '五级部门': ['五级部门'],
        '六级部门': ['六级部门'],
        '七级部门': ['七级部门'],
        '八级部门': ['八级部门'],
        '岗位': ['岗位', '职位'],
    }

    def __init__(self):
        self.salary_data: dict[str, dict] = {}

    @staticmethod
    def _cell(row, index: int, default=None):
        return row[index] if len(row) > index else default

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "").replace("$", "")
            if not cleaned:
                return default
            if cleaned.endswith("%"):
                cleaned = cleaned[:-1].strip()
                try:
                    return float(cleaned) / 100
                except (TypeError, ValueError):
                    return default
            try:
                return float(cleaned)
            except (TypeError, ValueError):
                return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _column_map_from_headers(cls, headers: list | tuple | None) -> dict[str, int]:
        if not headers:
            return dict(cls.COLUMN_MAP)
        normalized_headers = {
            str(header).strip(): index
            for index, header in enumerate(headers)
            if header is not None and str(header).strip()
        }
        column_map = dict(cls.COLUMN_MAP)
        for key, aliases in cls.COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in normalized_headers:
                    column_map[key] = normalized_headers[alias]
                    break
        return column_map

    def load(self, rows: list, headers: list | tuple | None = None) -> dict[str, dict]:
        """
        加载薪资档案数据

        Args:
            rows: 薪资档案数据行

        Returns:
            薪资数据 {employee_id: {hourly_rate, ratio}}
        """
        self.salary_data = {}
        column_map = self._column_map_from_headers(headers)

        for row in rows:
            if not row or self._cell(row, column_map['工号']) is None:
                continue

            emp_id = str(self._cell(row, column_map['工号'])).strip()
            department_parts = [
                str(value).strip()
                for key in ('二级部门', '三级部门', '四级部门', '五级部门', '六级部门', '七级部门', '八级部门')
                for value in [self._cell(row, column_map[key])]
                if value and str(value).strip()
            ]
            calculation_method = str(self._cell(row, column_map['绩效奖金计算方式']) or "").strip()
            fixed_performance_base = self._cell(row, column_map['月度绩效奖金基数'])
            hourly_rate = self._cell(row, column_map['时薪标准'])
            ratio = self._cell(row, column_map['绩效比例'])

            if emp_id and hourly_rate is not None and hourly_rate != "":
                ratio_value = self._to_float(ratio)
                # 绩效比例可能是百分比形式，需要转换
                if ratio_value > 1:
                    ratio_value = ratio_value / 100

                self.salary_data[emp_id] = {
                    'hourly_rate': self._to_float(hourly_rate),
                    'ratio': ratio_value,
                    'calculation_method': calculation_method,
                    'fixed_performance_base': self._to_float(fixed_performance_base, default=0.0),
                    'personnel_status': str(self._cell(row, column_map['人员状态']) or "").strip(),
                    'area': str(self._cell(row, column_map['划分区域']) or "").strip(),
                    'cost_owner': str(self._cell(row, column_map['成本归属']) or "").strip(),
                    'department': "-".join(department_parts),
                    'position': str(self._cell(row, column_map['岗位']) or "").strip(),
                }

        return self.salary_data

    def get_hourly_rate(self, employee_id: str, is_night_shift: bool = False) -> float:
        """获取时薪（夜班+1）"""
        base_rate = self.salary_data.get(employee_id, {}).get('hourly_rate', 0)
        return base_rate + 1 if is_night_shift else base_rate

    def get_ratio(self, employee_id: str) -> float:
        """获取绩效比例"""
        return self.salary_data.get(employee_id, {}).get('ratio', 0.0)
