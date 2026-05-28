# 海外劳务核对 — 匹配质量与抽取稳定性优化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升海外劳务报账核对的匹配准确率和抽取稳定性，减少误报和人工复核量。

**Architecture:** 改进三个核心模块：(1) 姓名相似度算法从序列比对改为 token-set 比对，适配 normalize_employee_name 的排序结果；(2) 质量阈值从固定百分比改为分层容忍度；(3) 未匹配候选建议复用改进后的匹配逻辑。改动集中在 `compare.py`，不改 API、不改前端、不改抽取逻辑。

**Tech Stack:** Python, pytest

**问题诊断（基于实际批次数据）：**
- 批次 `labor_20260528`：ONESOURCE 供应商，抽取失败（AI 未开启，正则不匹配）
- 批次 `labor_20260527_223149_397319`：1 PDF 员工 vs 1 Excel 员工，名字不同但实际同一人，匹配失败（exceptionCount=2）
- 多个批次 quality=warning：金额偏差 0.4% 就触发告警，过于敏感

---

### Task 1: 改进姓名相似度算法

**Files:**
- Modify: `bonus_platform/engine/labor/compare.py:173-175`
- Test: `tests/test_labor_api.py`

当前 `_name_similarity` 用 `SequenceMatcher` 做字符串序列比对，但 `normalize_employee_name` 已经把 token 排序了，序列比对反而降低准确率。改为 token-set 交集比。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_labor_api.py` 末尾添加：

```python
def test_name_similarity_handles_reordered_tokens():
    from bonus_platform.engine.labor.compare import _name_similarity
    # 排序后的 normalize 结果应该完全匹配
    assert _name_similarity("ALVAREZ MINCHACA ROSA", "ROSA ALVAREZ MINCHACA") > 0.9
    # 缩写/拼写变体应该有较高分数
    assert _name_similarity("ALVAREZ MITRACHE ROSS", "ROSA ALVAREZ MINCHACA") > 0.5
    # 完全不同的名字应该低分
    assert _name_similarity("JOHN SMITH", "ROSA ALVAREZ MINCHACA") < 0.3


def test_name_similarity_with_token_subset():
    from bonus_platform.engine.labor.compare import _name_similarity
    # 一方是另一方的子集（缺少中间名）
    assert _name_similarity("ALVAREZ ROSA", "ALVAREZ MINCHACA ROSA") > 0.7
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py::test_name_similarity_handles_reordered_tokens tests/test_labor_api.py::test_name_similarity_with_token_subset -v
```

- [ ] **Step 3: 实现改进**

修改 `bonus_platform/engine/labor/compare.py` 第 173-175 行：

```python
def _name_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_employee_name(left).split())
    right_tokens = set(normalize_employee_name(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    min_size = min(len(left_tokens), len(right_tokens))
    max_size = max(len(left_tokens), len(right_tokens))
    # 基础分：交集占较小集合的比例
    base = len(intersection) / min_size
    # 长 token 匹配奖励：最长 token 匹配说明姓氏对了
    left_longest = max(left_tokens, key=len) if left_tokens else ""
    right_longest = max(right_tokens, key=len) if right_tokens else ""
    longest_bonus = 0.15 if left_longest == right_longest else 0.0
    # 子集惩罚：交集占较大集合越少，惩罚越重
    coverage = len(intersection) / max_size
    return round(min(base * 0.7 + coverage * 0.3 + longest_bonus, 1.0), 3)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py::test_name_similarity_handles_reordered_tokens tests/test_labor_api.py::test_name_similarity_with_token_subset tests/test_labor_api.py::test_labor_compare_response_includes_candidate_matches -v
```

- [ ] **Step 5: 运行全量测试确认无回归**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add bonus_platform/engine/labor/compare.py tests/test_labor_api.py
git commit -m "fix: improve name similarity with token-set matching for sorted normalize results"
```

---

### Task 2: 改进模糊匹配阈值策略

**Files:**
- Modify: `bonus_platform/engine/labor/compare.py:177-186`

当前 `_fuzzy_totals_support_match` 硬编码三个阈值阶梯（0.88/0.72/0.65），对小金额和大金额用同样的绝对容差。改为相对+绝对混合容差。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_labor_api.py` 末尾添加：

```python
def test_fuzzy_match_tolerance_scales_with_amount():
    from bonus_platform.engine.labor.compare import _fuzzy_totals_support_match
    # 小金额：$700 差 $2.91 (0.4%)，高相似度应该通过
    pdf = {"name": "A", "hours": 31.19, "amount": 698.99}
    excel = {"name": "A", "hours": 31.19, "amount": 701.90}
    assert _fuzzy_totals_support_match(pdf, excel, 0.80, 0.01, 0.1) is True
    # 大金额：$150000 差 $7500 (5%)，低相似度不应该通过
    pdf2 = {"name": "A", "hours": 100, "amount": 150000}
    excel2 = {"name": "A", "hours": 100, "amount": 157500}
    assert _fuzzy_totals_support_match(pdf2, excel2, 0.66, 0.01, 0.1) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py::test_fuzzy_match_tolerance_scales_with_amount -v
```

- [ ] **Step 3: 实现改进**

修改 `bonus_platform/engine/labor/compare.py` 的 `_fuzzy_totals_support_match`：

```python
def _fuzzy_totals_support_match(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], score: float, amount_tolerance: float, hours_tolerance: float) -> bool:
    amount_delta = abs(round(pdf_group["amount"] - excel_group["amount"], 2))
    hours_delta = abs(round(pdf_group["hours"] - excel_group["hours"], 2))
    max_amount = max(abs(pdf_group["amount"]), abs(excel_group["amount"]), 1.0)
    relative_amount_diff = amount_delta / max_amount
    if score >= 0.85:
        return True
    if score >= 0.70 and relative_amount_diff <= 0.02 and hours_delta <= max(hours_tolerance, 0.5):
        return True
    if score >= 0.60 and relative_amount_diff <= 0.01 and hours_delta <= max(hours_tolerance, 0.2):
        return True
    return False
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add bonus_platform/engine/labor/compare.py tests/test_labor_api.py
git commit -m "fix: use relative amount tolerance in fuzzy matching for better cross-scale support"
```

---

### Task 3: 放宽质量告警阈值

**Files:**
- Modify: `bonus_platform/app.py:410-436`

当前 `_labor_extraction_quality` 用固定 5% 作为所有维度的告警阈值。实际数据中 0.4% 金额差异就触发 warning。改为分层阈值。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_labor_api.py` 末尾添加：

```python
def test_quality_check_tolerates_small_amount_drift():
    import bonus_platform.app as app_module
    # 0.4% 金额差异不应触发 warning
    quality = app_module._labor_extraction_quality({
        "pdfEmployeeCount": 1,
        "excelEmployeeCount": 1,
        "pdfHoursTotal": 31.19,
        "excelHoursTotal": 31.19,
        "pdfAmountTotal": 698.99,
        "excelAmountTotal": 701.90,
        "unmatchedPdfCount": 0,
        "unmatchedExcelCount": 0,
    })
    assert quality["level"] == "ok"
    # 10% 金额差异应该触发 warning
    quality2 = app_module._labor_extraction_quality({
        "pdfEmployeeCount": 100,
        "excelEmployeeCount": 100,
        "pdfHoursTotal": 5000,
        "excelHoursTotal": 5000,
        "pdfAmountTotal": 100000,
        "excelAmountTotal": 110000,
        "unmatchedPdfCount": 0,
        "unmatchedExcelCount": 0,
    })
    assert quality2["level"] == "warning"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py::test_quality_check_tolerates_small_amount_drift -v
```

- [ ] **Step 3: 实现改进**

修改 `bonus_platform/app.py` 的 `_labor_extraction_quality` 函数中的阈值：

```python
def _labor_extraction_quality(summary: dict) -> dict:
    pdf_count = int(summary.get("pdfEmployeeCount") or 0)
    excel_count = int(summary.get("excelEmployeeCount") or 0)
    unmatched_pdf = int(summary.get("unmatchedPdfCount") or 0)
    unmatched_excel = int(summary.get("unmatchedExcelCount") or 0)
    pdf_hours = float(summary.get("pdfHoursTotal") or 0)
    excel_hours = float(summary.get("excelHoursTotal") or 0)
    pdf_amount = float(summary.get("pdfAmountTotal") or 0)
    excel_amount = float(summary.get("excelAmountTotal") or 0)

    issues = []
    if excel_count and abs(pdf_count - excel_count) / excel_count > 0.10:
        issues.append(f"PDF员工数 {pdf_count} 与 Excel员工数 {excel_count} 偏差超过 10%。")
    if excel_count and (unmatched_pdf + unmatched_excel) / excel_count > 0.25:
        issues.append(f"未匹配员工 {unmatched_pdf + unmatched_excel} 人，超过 Excel人数的 25%。")
    if excel_hours and abs(pdf_hours - excel_hours) / excel_hours > 0.10:
        issues.append(f"总工时差异 {round(pdf_hours - excel_hours, 2)}，超过 Excel总工时的 10%。")
    if excel_amount:
        amount_drift = abs(pdf_amount - excel_amount) / excel_amount
        if amount_drift > 0.10:
            issues.append(f"总金额差异 {round(pdf_amount - excel_amount, 2)}，超过 Excel总金额的 10%。")

    if issues:
        return {
            "level": "warning",
            "message": "抽取质量存在风险，请复核 PDF 抽取明细后再使用差异报告。",
            "issues": issues,
        }
    return {"level": "ok", "message": "抽取质量检查通过。", "issues": []}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 5: 更新已有测试中对 quality warning 的断言**

检查 `test_labor_compare_records_extraction_quality_warning_for_misaligned_totals` 是否仍然通过（该测试用例中金额偏差 600%，仍应触发 warning）。

- [ ] **Step 6: Commit**

```bash
git add bonus_platform/app.py tests/test_labor_api.py
git commit -m "fix: relax extraction quality thresholds from 5% to 10% to reduce false warnings"
```

---

### Task 4: 未匹配候选建议使用改进后的匹配逻辑

**Files:**
- Modify: `bonus_platform/engine/labor/compare.py:195-232`

`_suggest_unmatched_candidates` 用 `_name_similarity` + 固定 0.70 阈值。Task 1 改进了相似度算法后，这里自动受益，但 0.70 阈值需要调整以适配新算法的分数分布。

- [ ] **Step 1: 写失败的测试**

```python
def test_candidate_suggestion_with_reordered_names():
    import bonus_platform.app as app_module
    from bonus_platform.engine.labor.models import LaborLineItem
    # 模拟：PDF 抽取的名字和 Excel 的名字 token 相同但顺序不同
    monkeypatch_set = [
        LaborLineItem(source_type="pdf_invoice", source_file="f.pdf", source_page_or_row="p1",
                      employee_id="", employee_name_raw="ALVAREZ MINCHACA ROSA",
                      hours=31.19, amount=701.90, currency="USD", confidence=0.95, evidence_text="")
    ]
    # 这个测试验证候选建议能捕获 token 重排的情况
    from bonus_platform.engine.labor.compare import _suggest_unmatched_candidates, _aggregate
    pdf = _aggregate(monkeypatch_set)
    excel_items = [
        LaborLineItem(source_type="offline_workbook", source_file="e.xlsx", source_page_or_row="Sheet1!2",
                      employee_id="", employee_name_raw="ROSA ALVAREZ MINCHACA",
                      hours=31.19, amount=701.90, currency="USD", confidence=1.0, evidence_text="")
    ]
    excel = _aggregate(excel_items)
    # 先构造一个 "PDF有Excel无" 和 "Excel有PDF无" 的 rows
    rows = [
        {"employeeKey": "name:ALVAREZ MINCHACA ROSA", "matchStatus": "PDF有Excel无"},
        {"employeeKey": "name:ALVAREZ MINCHACA ROSA", "matchStatus": "Excel有PDF无"},
    ]
    candidates = _suggest_unmatched_candidates(rows, pdf, excel)
    # 应该找到候选匹配
    assert len(candidates) > 0
```

- [ ] **Step 2: 运行测试确认当前行为**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py::test_candidate_suggestion_with_reordered_names -v
```

- [ ] **Step 3: 如果需要，调整候选阈值**

Task 1 的新 `_name_similarity` 对排序后的 token 集合会产生不同的分数分布。如果 0.70 阈值不再合适，调整为 0.55（因为新算法更严格，分数普遍偏低）：

```python
def _suggest_unmatched_candidates(rows, pdf, excel):
    # ... existing code ...
    for pdf_key in unmatched_pdf_keys:
        best = None
        for excel_key in unmatched_excel_keys:
            if excel_key in used_excel:
                continue
            pdf_group = pdf.get(pdf_key, _empty_group())
            excel_group = excel.get(excel_key, _empty_group())
            score = _name_similarity(pdf_group["name"], excel_group["name"])
            if score < 0.55:  # 从 0.70 调整为 0.55
                continue
            # ... rest unchanged ...
```

- [ ] **Step 4: 运行全量测试**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add bonus_platform/engine/labor/compare.py tests/test_labor_api.py
git commit -m "fix: adjust candidate suggestion threshold to match new token-set similarity scores"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 运行全量测试**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m pytest -q --tb=short
```

- [ ] **Step 2: 启动服务验证前端**

```bash
cd /Users/zt27532/Payroll-Automated-VC && python3 -m uvicorn bonus_platform.app:app --reload --port 8001
```

访问 `http://127.0.0.1:8001/overseas-labor.html`，创建新批次验证流程。

- [ ] **Step 3: 最终 Commit（如有修复）**

```bash
git add -A && git commit -m "chore: final adjustments after end-to-end verification"
```

---

## 不在本次范围内

- AI 抽取稳定性（需要配置 AI_ENABLED 和 API 密钥）
- 正则规则扩展覆盖更多供应商格式（需要实际 PDF 样本）
- 前端 UI 改动
- 报告格式改动
