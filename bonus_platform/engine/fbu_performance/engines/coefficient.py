"""FBU绩效核算引擎 - 绩效系数计算"""
from __future__ import annotations
from typing import Optional


class CoefficientCalculator:
    """绩效系数计算器"""

    # 职能端等级映射
    LEVEL_MAP = {
        '远低于预期': 0,
        '低于预期': 0.5,
        '符合预期-': 0.8,
        '符合预期': 1.0,
        '符合预期+': 1.2,
        '超出预期': 1.4,
        '远超预期': 1.6,
    }

    @staticmethod
    def calc_warehouse_coefficient(score: float) -> float:
        """
        仓库端：分段公式计算绩效系数

        - score ≤ 60        → 0
        - 60 < score ≤ 95   → score / 95
        - 95 < score ≤ 125  → 1 + 0.6 × (score - 95) / 30
        - score > 125       → 1.6（封顶）
        """
        if score is None:
            return 0.0
        if score <= 60:
            return 0.0
        elif score <= 95:
            return round(score / 95, 2)
        elif score <= 125:
            return round(1 + 0.6 * (score - 95) / 30, 2)
        else:
            return 1.6

    @classmethod
    def calc_functional_coefficient(cls, level: str) -> float:
        """职能端：等级映射绩效系数"""
        normalized_level = str(level).strip() if level is not None else ""
        return cls.LEVEL_MAP.get(normalized_level, 0.0)

    @classmethod
    def calculate(
        cls,
        job_type: str,
        score: Optional[float] = None,
        level: Optional[str] = None,
    ) -> float:
        """
        计算绩效系数

        Args:
            job_type: 岗位类型 (warehouse/functional)
            score: 绩效得分（仓库端）
            level: 绩效等级（职能端）

        Returns:
            绩效系数
        """
        if job_type == 'warehouse':
            return cls.calc_warehouse_coefficient(score)
        else:
            return cls.calc_functional_coefficient(level)
