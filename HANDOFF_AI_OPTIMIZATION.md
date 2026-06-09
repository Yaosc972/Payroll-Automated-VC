# AI 抽取优化 — 实施计划

## 4 项改动

### Phase 1: 智能页面筛选
- `extract.py`: 新增 `_select_invoice_pages()` — 无Profile时AI判断有效页，0页fallback全读
- `extract.py`: `_extract_with_ai_images()` 中分chunk前调用筛选
- `config.py`: AI_CONFIG 新增 `"smart_page_selection": True`

### Phase 2: 置信度驱动重试
- `app.py`: 新增 `_retry_low_confidence_rows()` — 局部重试低置信度行
- `app.py`: `_retry_if_better()` 先局部再全量
- `extract.py`: `_ai_instruction()` 新增 `retry_mode` 参数
- `quality.py`: 返回值新增 `lowConfidenceRows`

### Phase 3: 自动生成 Profile
- `profiles.py`: 新增 `generate_profile_from_extraction()`, `save_supplier_profile()`
- `profiles.py`: `resolve_supplier_profile()` 优先读动态Profile
- `app.py`: Stage 2 成功后调用生成

### Phase 4: 格式变化自动检测
- `extract.py`: 新增 `_check_profile_validity()` — 规则抽0行→标记失效
- `profiles.py`: Profile新增 `version`, `failure_count` 字段
- `app.py`: 记录失效事件，触发重建

## 技术债务修复
- D7: profiles.py 加载失败加 warning
- D11: confidence 默认值对齐阈值
- D16: 硬编码条件加注释

## 依赖顺序
Phase 1 → Phase 3 → Phase 2 → Phase 4

## 状态
- [x] Phase 1 — 智能页面筛选 ✅
- [x] Phase 2 — 置信度驱动重试 ✅
- [x] Phase 3 — 自动生成 Profile ✅
- [x] Phase 4 — 格式变化自动检测 ✅
- [x] 技术债务 D7/D11/D16 ✅
- [x] 单元测试 17 个新增 ✅（111/111 通过）
