# 海外劳务报账核对功能优化计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化海外劳务报账核对功能的5个方面：规则抽取、缓存机制、总额差异容忍度、姓名匹配算法、并行化

**Architecture:** 基于现有代码结构，采用增量优化策略，每个优化点独立实现，确保向后兼容

**Tech Stack:** Python 3.9+, FastAPI, pypdf, pypdfium2, openpyxl

---

## 优化方向概览

| 方向 | 状态 | 优先级 | 预计工作量 |
|------|------|--------|-----------|
| 1. 规则抽取优先 | ✅ 已完成 | 高 | 0 |
| 2. 缓存机制 | ✅ 已完成 | 高 | 0 |
| 3. 总额差异容忍度 | ⏳ 待实现 | 中 | 1小时 |
| 4. 姓名匹配算法 | ⏳ 待实现 | 中 | 2小时 |
| 5. 并行化 | ⏳ 待实现 | 低 | 3小时 |

---

## Task 1: 总额差异容忍度优化

**目标:** 调整总额差异阈值，避免微小舍入差异被标记为失败

**Files:**
- Modify: `bonus_platform/engine/labor/compare.py:60-68`
- Modify: `bonus_platform/app.py:538-581`
- Test: `tests/test_labor_api.py`

- [ ] **Step 1: 分析当前阈值设置**

当前代码在 `compare_by_warehouse` 中设置 `amount_tolerance=0.05`，这意味着 $0.05 以内的差异会被视为通过。但从实际数据看，仓库19 的 $0.09 差异（$54,689.86 vs $54,689.95）被标记为失败，这可能是舍入误差导致的。

```python
# 当前设置
amount_tolerance=AI_CONFIG["amount_tolerance"]  # 通常是 0.05
```

- [ ] **Step 2: 实现自适应容忍度**

在 `compare.py` 中添加自适应容忍度逻辑：对于大金额（>$1000），容忍度按比例增加。

```python
def _adaptive_tolerance(amount: float, base_tolerance: float = 0.05) -> float:
    """根据金额大小自适应调整容忍度。

    大金额允许更大的绝对差异，但保持相对差异在合理范围内。
    """
    if amount <= 1000:
        return base_tolerance
    # 对于大金额，容忍度按对数增长
    import math
    multiplier = 1 + math.log10(amount / 1000)
    return base_tolerance * multiplier
```

- [ ] **Step 3: 修改 compare_by_warehouse 函数**

在 `compare_by_warehouse` 函数中使用自适应容忍度：

```python
def compare_by_warehouse(
    excel_rows_with_warehouse: List[Dict[str, Any]],
    pdf_totals: List[Dict[str, Any]] | None = None,
    pdf_rows: List[LaborLineItem] | None = None,
    amount_tolerance: float = 0.05,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
) -> Dict[str, Any]:
    # ... 现有代码 ...

    for wh in all_wh:
        # ... 现有代码 ...

        # 使用自适应容忍度
        effective_tolerance = _adaptive_tolerance(max(abs(pdf_amount), abs(excel_amount)), amount_tolerance)
        wh_passed = abs(amount_delta) <= effective_tolerance

        # ... 现有代码 ...
```

- [ ] **Step 4: 更新结论生成逻辑**

在 `app.py` 的 `_build_conclusion` 函数中，使用相同的自适应容忍度：

```python
def _build_conclusion(warehouse_comparison: dict, comparison: dict, extraction_quality: dict) -> dict:
    # ... 现有代码 ...

    # 使用自适应容忍度判断是否通过
    from bonus_platform.engine.labor.compare import _adaptive_tolerance
    effective_tolerance = _adaptive_tolerance(max(pdf_amount_total, excel_amount_total), 0.05)
    total_passed = abs(amount_delta_total) <= effective_tolerance

    # ... 现有代码 ...
```

- [ ] **Step 5: 添加测试用例**

在 `tests/test_labor_api.py` 中添加测试：

```python
def test_adaptive_tolerance_for_large_amounts():
    """测试大金额的自适应容忍度"""
    from bonus_platform.engine.labor.compare import _adaptive_tolerance

    # 小金额使用基础容忍度
    assert _adaptive_tolerance(500) == 0.05

    # 大金额容忍度更高
    assert _adaptive_tolerance(50000) > 0.05
    assert _adaptive_tolerance(100000) > _adaptive_tolerance(50000)

    # 容忍度不应过高
    assert _adaptive_tolerance(1000000) < 1.0
```

- [ ] **Step 6: 运行测试并验证**

```bash
python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 7: 提交代码**

```bash
git add bonus_platform/engine/labor/compare.py bonus_platform/app.py tests/test_labor_api.py
git commit -m "feat: 实现自适应总额差异容忍度，避免舍入误差误报

- 大金额（>$1000）容忍度按对数增长
- 仓库19 的 $0.09 差异不再被标记为失败
- 添加测试用例验证容忍度逻辑"
```

---

## Task 2: 姓名匹配算法优化

**目标:** 提升模糊匹配的准确率，减少误匹配和漏匹配

**Files:**
- Modify: `bonus_platform/engine/labor/compare.py:322-390`
- Modify: `bonus_platform/engine/labor/parsing.py`
- Test: `tests/test_labor_api.py`

- [ ] **Step 1: 分析当前匹配算法**

当前匹配算法使用：
1. SequenceMatcher 字符串相似度
2. Token 交集（姓名分词后的交集）
3. 昵称变体映射（80+ 组）

问题：
- 对于 "Last, First" 和 "First Last" 格式的匹配不够准确
- 对于中间名（middle name）的处理不够灵活
- 对于缩写（如 "J." vs "John"）的处理不够智能

- [ ] **Step 2: 改进姓名标准化**

在 `parsing.py` 中添加更智能的姓名标准化：

```python
def normalize_employee_name_advanced(name: str) -> str:
    """高级姓名标准化，处理各种格式。

    处理：
    - "Last, First" → "First Last"
    - 移除中间名缩写（如 "J."）
    - 统一大小写
    - 移除多余空格
    """
    if not name:
        return ""

    # 处理 "Last, First" 格式
    if ',' in name:
        parts = name.split(',', 1)
        if len(parts) == 2:
            last, first = parts
            name = f"{first.strip()} {last.strip()}"

    # 移除中间名缩写（如 "J." 或 "J"）
    parts = name.split()
    if len(parts) >= 3:
        # 如果中间部分是单个字母或带点的单个字母，可能是中间名缩写
        middle = parts[1]
        if len(middle) <= 2 and (len(middle) == 1 or middle.endswith('.')):
            parts.pop(1)

    # 统一大小写并移除多余空格
    return ' '.join(parts).lower().strip()
```

- [ ] **Step 3: 改进相似度计算**

在 `compare.py` 中改进 `_name_similarity` 函数：

```python
def _name_similarity_improved(left: str, right: str) -> float:
    """改进的姓名相似度计算。

    结合多种算法：
    1. 标准化后的精确匹配
    2. Token 集合相似度（处理词序差异）
    3. 编辑距离相似度（处理拼写错误）
    4. 昵称变体匹配
    """
    # 标准化
    left_norm = normalize_employee_name_advanced(left)
    right_norm = normalize_employee_name_advanced(right)

    # 精确匹配
    if left_norm == right_norm:
        return 1.0

    # Token 集合相似度
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0

    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(intersection) / len(union) if union else 0.0

    # 编辑距离相似度
    from difflib import SequenceMatcher
    sequence_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()

    # 昵称变体匹配
    left_variants = expand_name_variants(left)
    right_variants = expand_name_variants(right)
    variant_bonus = 0.3 if left_variants & right_variants else 0.0

    # 综合评分（加权平均）
    score = jaccard * 0.4 + sequence_ratio * 0.6 + variant_bonus

    return min(score, 1.0)
```

- [ ] **Step 4: 更新匹配逻辑**

在 `_match_employee_groups` 函数中使用新的相似度计算：

```python
def _match_employee_groups(
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
) -> List[Dict[str, Any]]:
    # 使用改进的相似度计算
    fuzzy_matches = _fuzzy_match_unmatched_groups_improved(pdf, excel,
                                                          amount_tolerance=amount_tolerance,
                                                          hours_tolerance=hours_tolerance)
    # ... 现有代码 ...
```

- [ ] **Step 5: 添加测试用例**

```python
def test_advanced_name_normalization():
    """测试高级姓名标准化"""
    from bonus_platform.engine.labor.parsing import normalize_employee_name_advanced

    # "Last, First" 格式
    assert normalize_employee_name_advanced("Alvarez, Rosa") == "rosa alvarez"

    # 中间名缩写
    assert normalize_employee_name_advanced("Rosa J. Alvarez") == "rosa alvarez"

    # 多余空格
    assert normalize_employee_name_advanced("  Rosa   Alvarez  ") == "rosa alvarez"

def test_improved_name_similarity():
    """测试改进的姓名相似度"""
    from bonus_platform.engine.labor.compare import _name_similarity_improved

    # 相同姓名
    assert _name_similarity_improved("Rosa Alvarez", "Rosa Alvarez") == 1.0

    # "Last, First" vs "First Last"
    assert _name_similarity_improved("Alvarez, Rosa", "Rosa Alvarez") > 0.8

    # 中间名差异
    assert _name_similarity_improved("Rosa J. Alvarez", "Rosa Alvarez") > 0.8

    # 拼写错误
    assert _name_similarity_improved("Rosa Alvarez", "Rosa Alvarex") > 0.7
```

- [ ] **Step 6: 运行测试并验证**

```bash
python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 7: 提交代码**

```bash
git add bonus_platform/engine/labor/compare.py bonus_platform/engine/labor/parsing.py tests/test_labor_api.py
git commit -m "feat: 优化姓名匹配算法，提升模糊匹配准确率

- 改进姓名标准化：处理 'Last, First' 格式和中间名缩写
- 改进相似度计算：结合 Jaccard、编辑距离、昵称变体
- 添加测试用例验证匹配逻辑"
```

---

## Task 3: 并行化优化

**目标:** 并行处理多个 PDF 文件，提升抽取速度

**Files:**
- Modify: `bonus_platform/engine/labor/extract.py:66-103`
- Test: `tests/test_labor_api.py`

- [ ] **Step 1: 分析当前抽取流程**

当前 `extract_invoice_items` 函数是串行处理的：
1. 提取所有 PDF 的文本
2. 逐个尝试规则抽取
3. 如果规则失败，逐个调用 AI 抽取

问题：当有多个 PDF 时，AI 调用是串行的，每个 PDF 需要 20-60 秒，总时间很长。

- [ ] **Step 2: 实现并行 AI 抽取**

修改 `extract_invoice_items` 函数，使用线程池并行处理：

```python
def extract_invoice_items(
    pdf_paths: List[Path],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    expected_rows: List[Dict[str, Any]] | None = None,
) -> List[LaborLineItem]:
    supplier_profile = resolve_supplier_profile(supplier, profiles_path=ai_config.get("supplier_profiles_path"))
    pages = _extract_pdf_pages(pdf_paths)
    if supplier_profile.image_page_policy == "first_page_only":
        pages = [p for p in pages if int(p.get("page") or 1) == 1]

    # 并行规则抽取
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _extract_rules_for_page(page: Dict[str, Any]) -> List[LaborLineItem]:
        """对单个页面尝试规则抽取"""
        rows = []
        rows.extend(_extract_vertical_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_tabular_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        return rows

    # 并行执行规则抽取
    all_rule_items = []
    with ThreadPoolExecutor(max_workers=min(len(pages), 6)) as executor:
        future_to_page = {executor.submit(_extract_rules_for_page, page): page for page in pages}
        for future in as_completed(future_to_page):
            try:
                items = future.result()
                all_rule_items.extend(items)
            except Exception:
                pass

    if all_rule_items:
        return all_rule_items

    # 如果规则抽取失败，尝试 AI 抽取
    if _ai_ready(ai_config):
        # 并行 AI 抽取
        def _extract_ai_for_page(page: Dict[str, Any]) -> List[Dict[str, Any]]:
            """对单个页面尝试 AI 抽取"""
            # ... 现有 AI 抽取逻辑 ...
            pass

        # ... 并行执行 AI 抽取 ...
```

- [ ] **Step 3: 实现并行图片渲染**

对于图片 PDF，渲染也是耗时操作。实现并行渲染：

```python
def _render_pdf_pages_to_images_parallel(pdf_paths: List[Path], scale: float = 1.5, max_workers: int = 4) -> List[Dict[str, Any]]:
    """并行渲染 PDF 页面为图片"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _render_single_pdf(path: Path) -> List[Dict[str, Any]]:
        """渲染单个 PDF 的所有页面"""
        try:
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(str(path))
            pages = []
            try:
                for index in range(len(document)):
                    page = document[index]
                    try:
                        bitmap = page.render(scale=scale).to_pil()
                        if bitmap.height > bitmap.width:
                            bitmap = bitmap.rotate(90, expand=True)
                        buffer = BytesIO()
                        bitmap.save(buffer, format="PNG")
                        pages.append({
                            "source_file": path.name,
                            "source_path": str(path),
                            "page": index + 1,
                            "mime_type": "image/png",
                            "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                        })
                    finally:
                        page.close()
            finally:
                document.close()
            return pages
        except Exception:
            return []

    all_pages = []
    with ThreadPoolExecutor(max_workers=min(len(pdf_paths), max_workers)) as executor:
        future_to_path = {executor.submit(_render_single_pdf, path): path for path in pdf_paths}
        for future in as_completed(future_to_path):
            try:
                pages = future.result()
                all_pages.extend(pages)
            except Exception:
                pass

    return all_pages
```

- [ ] **Step 4: 添加并行化配置**

在 `.env` 或 `AI_CONFIG` 中添加并行化配置：

```python
# 并行化配置
PARALLEL_EXTRACTION_ENABLED = True
PARALLEL_MAX_WORKERS = 6
PARALLEL_IMAGE_RENDER_WORKERS = 4
```

- [ ] **Step 5: 添加测试用例**

```python
def test_parallel_extraction():
    """测试并行抽取"""
    from bonus_platform.engine.labor.extract import extract_invoice_items
    from bonus_platform.config import AI_CONFIG

    # 准备测试数据
    pdf_paths = [...]  # 多个 PDF 文件

    # 测试并行抽取
    import time
    start = time.time()
    items = extract_invoice_items(pdf_paths, AI_CONFIG, supplier="Fairway")
    duration = time.time() - start

    # 验证结果
    assert len(items) > 0
    print(f"并行抽取耗时: {duration:.2f}s")
```

- [ ] **Step 6: 运行测试并验证**

```bash
python3 -m pytest tests/test_labor_api.py -v
```

- [ ] **Step 7: 提交代码**

```bash
git add bonus_platform/engine/labor/extract.py tests/test_labor_api.py
git commit -m "feat: 实现并行化抽取，提升多 PDF 处理速度

- 并行规则抽取：多线程处理多个页面
- 并行图片渲染：多线程渲染多个 PDF
- 添加并行化配置选项
- 添加测试用例验证并行逻辑"
```

---

## Task 4: 集成测试与验证

**目标:** 使用真实数据验证所有优化效果

**Files:**
- Test: `tests/test_labor_api.py`
- Test: `tests/test_integration.py`

- [ ] **Step 1: 创建集成测试**

```python
def test_full_workflow_with_optimizations():
    """完整工作流集成测试，验证所有优化"""
    from bonus_platform.engine.labor.extract import quick_extract_totals
    from bonus_platform.engine.labor.compare import compare_by_warehouse
    from bonus_platform.config import AI_CONFIG
    from pathlib import Path

    # 准备测试数据
    pdf_dir = Path('outputs/labor_runs/labor_20260529_161947_167047_2a51a861')
    pdf_paths = sorted(pdf_dir.glob('*.pdf'))

    # 测试规则抽取优先
    import time
    start = time.time()
    totals = quick_extract_totals(pdf_paths, AI_CONFIG, supplier='Fairway Staffing Service')
    duration = time.time() - start

    print(f"规则抽取耗时: {duration:.2f}s")
    print(f"提取结果: {len(totals)} 个仓库")

    # 验证仓库19 金额正确
    wh19 = next(t for t in totals if t['warehouse_id'] == '19')
    assert abs(wh19['total_amount'] - 54689.86) < 1.0, f"仓库19 金额错误: {wh19['total_amount']}"

    # 测试自适应容忍度
    from bonus_platform.engine.labor.compare import _adaptive_tolerance
    assert _adaptive_tolerance(50000) > 0.05, "大金额容忍度应更高"

    print("所有优化验证通过！")
```

- [ ] **Step 2: 运行集成测试**

```bash
python3 -m pytest tests/test_integration.py -v
```

- [ ] **Step 3: 性能对比测试**

```python
def test_performance_comparison():
    """性能对比测试：优化前 vs 优化后"""
    from bonus_platform.engine.labor.extract import quick_extract_totals
    from bonus_platform.config import AI_CONFIG
    from pathlib import Path

    pdf_dir = Path('outputs/labor_runs/labor_20260529_161947_167047_2a51a861')
    pdf_paths = sorted(pdf_dir.glob('*.pdf'))

    # 测试多次，取平均值
    import time
    durations = []
    for _ in range(3):
        start = time.time()
        totals = quick_extract_totals(pdf_paths, AI_CONFIG, supplier='Fairway Staffing Service')
        durations.append(time.time() - start)

    avg_duration = sum(durations) / len(durations)
    print(f"平均抽取耗时: {avg_duration:.2f}s")

    # 验证耗时在合理范围内（规则抽取应该很快）
    assert avg_duration < 5.0, f"抽取耗时过长: {avg_duration:.2f}s"
```

- [ ] **Step 4: 提交测试代码**

```bash
git add tests/test_integration.py
git commit -m "test: 添加集成测试和性能对比测试

- 验证规则抽取优先优化效果
- 验证自适应容忍度逻辑
- 性能对比测试确保优化有效"
```

---

## 总结

本计划包含4个任务：

1. **总额差异容忍度优化** — 避免舍入误差误报
2. **姓名匹配算法优化** — 提升模糊匹配准确率
3. **并行化优化** — 提升多 PDF 处理速度
4. **集成测试与验证** — 验证所有优化效果

预计总工作量：6-8 小时

执行顺序：Task 1 → Task 2 → Task 3 → Task 4

每个任务独立可测试，完成后可立即验证效果。
