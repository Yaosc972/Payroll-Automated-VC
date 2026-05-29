"""集成测试：使用真实数据验证所有优化效果。

覆盖：
1. 规则抽取优先 — 仓库19 金额从 $1,234.56 修正为 ~$54,689.86
2. 自适应容忍度 — 大金额容忍度更高
3. 并行化 — 多 PDF 并行处理
"""

import math
import time
from pathlib import Path

import pytest

from bonus_platform.config import AI_CONFIG
from bonus_platform.engine.labor.compare import _adaptive_tolerance
from bonus_platform.engine.labor.extract import quick_extract_totals

# 使用真实数据目录
REAL_DATA_DIR = Path(
    "outputs/labor_runs/labor_20260529_161947_167047_2a51a861"
)


@pytest.fixture(scope="module")
def pdf_paths():
    """收集测试目录下所有 PDF 文件路径。"""
    paths = sorted(REAL_DATA_DIR.glob("*.pdf"))
    assert len(paths) > 0, f"测试目录下无 PDF 文件: {REAL_DATA_DIR}"
    return paths


@pytest.fixture(scope="module")
def extraction_results(pdf_paths):
    """运行一次规则抽取，所有测试共用结果。"""
    totals = quick_extract_totals(
        pdf_paths, AI_CONFIG, supplier="Fairway Staffing Service"
    )
    assert len(totals) > 0, "抽取结果为空"
    return totals


# ---------------------------------------------------------------------------
# 测试 1: 完整工作流集成测试
# ---------------------------------------------------------------------------


class TestFullWorkflowWithOptimizations:
    """完整工作流集成测试，验证所有优化效果。"""

    def test_rule_extraction_returns_results(self, extraction_results):
        """规则抽取应返回有效的仓库和金额数据。"""
        assert len(extraction_results) > 0
        for item in extraction_results:
            assert "source_file" in item
            assert "total_amount" in item
            assert "warehouse_id" in item

    def test_warehouse_19_amount_correct(self, extraction_results):
        """仓库19 金额应修正为 ~$54,689.86（而非旧的 $1,234.56）。"""
        wh19_items = [
            t for t in extraction_results if t.get("warehouse_id") == "19"
        ]
        assert len(wh19_items) > 0, "未找到仓库19的数据"

        total_19 = sum(t["total_amount"] for t in wh19_items)
        # 仓库19 金额应在 $54,689 附近，而非旧值 $1,234.56
        assert total_19 > 10000, (
            f"仓库19 金额异常偏低: ${total_19:.2f}，"
            f"可能仍使用旧的错误抽取逻辑 ($1,234.56)"
        )
        assert abs(total_19 - 54689.86) < 10.0, (
            f"仓库19 金额不正确: ${total_19:.2f}，期望 ~$54,689.86"
        )

    def test_warehouse_28_amount_correct(self, extraction_results):
        """仓库28 金额应为 ~$24,936.43。"""
        wh28_items = [
            t for t in extraction_results if t.get("warehouse_id") == "28"
        ]
        if not wh28_items:
            pytest.skip("测试数据中无仓库28")
        total_28 = sum(t["total_amount"] for t in wh28_items)
        assert abs(total_28 - 24936.43) < 1.0, (
            f"仓库28 金额不正确: ${total_28:.2f}"
        )

    def test_all_warehouses_have_positive_amounts(self, extraction_results):
        """所有仓库金额应大于 0。"""
        for item in extraction_results:
            if item["warehouse_id"]:  # 仅检查有仓库号的
                assert item["total_amount"] > 0, (
                    f"{item['source_file']} 仓库 {item['warehouse_id']} "
                    f"金额为 ${item['total_amount']:.2f}"
                )


# ---------------------------------------------------------------------------
# 测试 2: 自适应容忍度
# ---------------------------------------------------------------------------


class TestAdaptiveTolerance:
    """验证自适应容忍度逻辑。"""

    def test_small_amount_uses_base_tolerance(self):
        """小金额 (<= $1,000) 使用基础容忍度。"""
        tol = _adaptive_tolerance(500)
        assert tol == pytest.approx(0.05)

    def test_large_amount_tolerance_higher(self):
        """大金额 ($50,000) 容忍度应高于基础值。"""
        tol = _adaptive_tolerance(50000)
        assert tol > 0.05, f"大金额容忍度应更高，实际: {tol}"

    def test_tolerance_increases_with_amount(self):
        """容忍度应随金额增大而增加。"""
        tol_1k = _adaptive_tolerance(1000)
        tol_10k = _adaptive_tolerance(10000)
        tol_100k = _adaptive_tolerance(100000)
        assert tol_1k <= tol_10k <= tol_100k

    def test_custom_base_tolerance(self):
        """自定义基础容忍度应正确应用。"""
        tol = _adaptive_tolerance(500, base_tolerance=0.10)
        assert tol == pytest.approx(0.10)

    def test_logarithmic_growth(self):
        """大金额容忍度按对数增长。"""
        # $10,000: multiplier = 1 + log10(10) = 1 + 1 = 2
        tol_10k = _adaptive_tolerance(10000, base_tolerance=0.05)
        assert tol_10k == pytest.approx(0.10)

        # $100,000: multiplier = 1 + log10(100) = 1 + 2 = 3
        tol_100k = _adaptive_tolerance(100000, base_tolerance=0.05)
        assert tol_100k == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# 测试 3: 性能对比测试
# ---------------------------------------------------------------------------


class TestPerformance:
    """性能测试：确保优化后抽取速度在合理范围内。"""

    def test_extraction_speed(self, pdf_paths):
        """规则抽取应快速完成（< 5秒）。"""
        durations = []
        for _ in range(3):
            start = time.time()
            quick_extract_totals(
                pdf_paths, AI_CONFIG, supplier="Fairway Staffing Service"
            )
            durations.append(time.time() - start)

        avg_duration = sum(durations) / len(durations)
        print(f"\n  平均抽取耗时: {avg_duration:.2f}s")
        print(f"  各次耗时: {[f'{d:.2f}s' for d in durations]}")

        assert avg_duration < 5.0, (
            f"抽取耗时过长: {avg_duration:.2f}s，规则抽取应 < 5s"
        )

    def test_extraction_deterministic(self, pdf_paths):
        """多次抽取结果应一致（确定性）。"""
        results_1 = quick_extract_totals(
            pdf_paths, AI_CONFIG, supplier="Fairway Staffing Service"
        )
        results_2 = quick_extract_totals(
            pdf_paths, AI_CONFIG, supplier="Fairway Staffing Service"
        )

        # 按 source_file 排序后比较
        r1 = sorted(results_1, key=lambda x: x["source_file"])
        r2 = sorted(results_2, key=lambda x: x["source_file"])

        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a["source_file"] == b["source_file"]
            assert abs(a["total_amount"] - b["total_amount"]) < 0.01, (
                f"{a['source_file']}: "
                f"{a['total_amount']} vs {b['total_amount']}"
            )
            assert a["warehouse_id"] == b["warehouse_id"]
