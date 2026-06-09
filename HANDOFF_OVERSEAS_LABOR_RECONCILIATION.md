# 海外劳务工报账核对模块 — 交接文档

> 最后更新：2026-06-09  
> 分支：`claude/handoff-01`  
> 作者：AI 辅助开发 + 人工验收

---

## 1. 模块完成度总览

### ✅ 已完成

| 功能 | 说明 |
|------|------|
| 多文件上传 | 支持多个 PDF 发票 + 多个 Excel 账单同时上传 |
| Excel 多 Sheet 解析 | 用户选择工作表，自动检测列名，支持 .xlsx/.xlsm/.xls |
| 字段映射向导 | 3 步 Wizard（批次信息 → 上传文件 → 字段映射），带预览 |
| 智能页面筛选 | Phase 1 — 无 Profile 时用 AI 判断哪些页面包含计费数据 |
| 规则抽取 | 从 PDF 文本层提取员工行（Wage Code 格式） |
| AI 图片抽取 | 用 MiMo 视觉模型从 PDF 图片中提取员工数据 |
| 员工名清洗 | 去掉工号（CUE1PK2）、岗位后缀（Forklift Shift）等非姓名内容 |
| 行级过滤 | 丢弃非员工行（Workforce Shift、Open, Open 等汇总行） |
| 总额比对 | PDF 总金额 vs Excel 总金额，按仓库维度 |
| 员工明细比对 | 按姓名匹配，支持模糊匹配（OCR 错误容忍） |
| Excel 行聚合 | 同一员工多天记录自动合并后再比对 |
| 仓库维度比对 | 按仓库号分组核对金额差异 |
| 置信度驱动重试 | 低置信度行局部重试，失败再全量重试 |
| 自动生成 Profile | Stage 2 成功后自动保存供应商 Profile JSON |
| 格式变化检测 | Profile 失效计数，连续 3 次失败标记 deprecated |
| 差异报告导出 | 生成 Excel 格式的差异报告，含多 Sheet |
| 质量诊断 | 抽取质量评估（ok/warning/critical）+ 低置信度行明细 |
| 核对结论 | 自动判断 pass/warning/critical 级别 |

### ⏳ 半成品 / 有限可用

| 功能 | 状态 | 说明 |
|------|------|------|
| Token Plan 多页支持 | ⚠️ 受限 | API URL 含 "token-plan" 时强制每页单独请求，4 PDF 约需 20-30 分钟 |
| Profile 自动生成 | ⚠️ 条件触发 | 仅 quality=ok 时生成，当前多数运行质量为 warning 故未生成 |
| 智能页面筛选 | ⚠️ 条件触发 | 仅 DEFAULT_PROFILE 时触发，有 Profile 时跳过 |

### ❌ 未开始

| 功能 | 说明 |
|------|------|
| 国内劳务工核对 | 有独立的 `domestic-labor` API 和页面，但与本模块无关 |
| 历史批次对比 | 不支持跨批次趋势分析 |
| 自动发送报告 | 无邮件/通知集成 |
| 多语言界面 | 仅中文 |

---

## 2. 相关文件清单

### 后端引擎（`bonus_platform/engine/labor/`）

| 文件 | 行数 | 职责 |
|------|------|------|
| `__init__.py` | 2 | 包初始化 |
| `models.py` | 109 | `LaborLineItem` 数据模型（员工行） |
| `extract.py` | 1979 | **核心**：PDF 抽取（规则 + AI），页面筛选，名字清洗 |
| `compare.py` | 683 | 员工比对逻辑，模糊匹配，金额差异计算 |
| `quality.py` | 332 | 抽取质量评估，低置信度行统计 |
| `profiles.py` | 291 | 供应商 Profile 管理（内置 + 动态生成） |
| `layout.py` | 285 | PDF 布局分析（识别表格结构） |
| `parsing.py` | 216 | 数字解析，姓名标准化（Workbuddy 格式等） |
| `workbook.py` | 190 | Excel 解析，表头检测，字段映射 |
| `report.py` | 318 | 差异报告生成（Excel 格式） |
| `runs.py` | 97 | 运行记录元数据管理 |

### 后端 API（`bonus_platform/app.py` 中的 labor 路由）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/labor/runs` | GET | 列出所有批次 |
| `/api/labor/runs` | POST | 创建新批次 |
| `/api/labor/runs/{id}` | GET | 获取批次详情 |
| `/api/labor/runs/{id}/files` | POST | 上传 PDF/Excel 文件 |
| `/api/labor/runs/{id}/workbook-sheets` | GET | 列出 Excel 工作表 |
| `/api/labor/runs/{id}/field-suggestions` | POST | 自动推荐字段映射 |
| `/api/labor/runs/{id}/mapping` | POST | 保存字段映射 |
| `/api/labor/runs/{id}/extract-and-compare` | POST | 触发抽取并比对 |
| `/api/labor/runs/{id}/download/{filename}` | GET | 下载报告文件 |

### 前端（`bonus_platform/static/`）

| 文件 | 行数 | 职责 |
|------|------|------|
| `overseas-labor.html` | 438 | 页面结构：KPI 横幅 + 工作区 + Wizard 抽屉 |
| `overseas-labor.js` | 1107 | 核心逻辑：API 调用、表格渲染、状态轮询 |
| `styles.css` | ~8000 | 全站样式（含其他模块） |

### 配置

| 文件 | 说明 |
|------|------|
| `bonus_platform/config.py` | AI_CONFIG、OUTPUT_DIR、LABOR_RUNS_DIR |
| `data/supplier_profiles/invoice.json` | 动态生成的 Invoice 供应商 Profile |
| `data/supplier_profiles/onesource.json` | 动态生成的 OneSource 供应商 Profile |

### 测试

| 文件 | 行数 | 说明 |
|------|------|------|
| `tests/test_labor_engine.py` | 1981 | 引擎单元测试（含 Phase 2/3/4 的 17 个新测试） |
| `tests/test_labor_api.py` | 665 | API 集成测试 |

### 运行数据

| 目录 | 说明 |
|------|------|
| `outputs/labor_runs/` | 所有批次的运行数据（PDF、Excel、元数据、报告） |

---

## 3. 业务流程

```
用户操作                          系统处理
─────────                        ─────────
1. 新建批次                       → 生成 run_id，记录供应商/账期/币种
   填写供应商名称、账期、币种

2. 上传文件                       → PDF 和 Excel 存入 run 目录
   PDF 发票（支持多文件）
   Excel 账单（支持多文件）

3. 选择工作表 + 字段映射          → 读取 Excel 列名，用户指定
   name / hours / amount /        name→哪列，hours→哪列，amount→哪列
   employeeId / currency

4. 点击「抽取并比对」             → 后台异步执行：
                                   a. Excel 解析 + 行聚合（同员工多天合并）
                                   b. Stage 1: 快速总金额抽取
                                   c. 仓库维度比对
                                   d. Stage 2: AI 员工明细抽取（如需）
                                   e. 员工级比对（模糊匹配）
                                   f. 质量评估 + 重试（如需）
                                   g. 生成差异报告

5. 查看结果                       → 前端轮询展示：
   KPI 横幅（总额/差额/待复核）    - 全员对账明细表
   全员对账明细                    - 质量诊断
   仓库核对总览                    - 待处理事项分组
   待处理事项
   下载 Excel 报告
```

### 输出物

- **差异报告 Excel**：含多个 Sheet（员工比对、仓库汇总、异常明细）
- **前端实时展示**：KPI 卡片 + 可交互的比对明细表
- **质量评估**：ok/warning/critical 级别 + 问题列表

---

## 4. 已实现的核对规则

### 4.1 人员匹配

| 匹配方式 | 说明 |
|----------|------|
| 精确匹配 | PDF 员工名 = Excel 员工名（大小写不敏感） |
| 模糊匹配 | 基于 SequenceMatcher，阈值 0.6，需金额差异 < 容差 |
| Workbuddy 格式 | 处理 "名 姓" → "姓, 名" 的转换 |
| 姓名标准化 | 去除重音符号、标点、多余空格 |
| 候选匹配 | 当精确匹配失败时，推荐最可能的匹配对 |

### 4.2 金额核对

| 规则 | 说明 |
|------|------|
| 总金额比对 | PDF 总额 vs Excel 总额，容差 $0.10 |
| 员工金额比对 | 每人 amount 差异，标记 "差异" 状态 |
| 仓库维度比对 | 按 warehouse_id 分组汇总后比对 |
| 自适应容差 | 大金额（>$1000）自动放宽容差到 1% |

### 4.3 工时核对

| 规则 | 说明 |
|------|------|
| 工时差异 | PDF hours vs Excel hours，标记风险 |
| 工时为 0 但金额 > 0 | 标记为 meal premium，不视为异常 |

### 4.4 质量评估

| 指标 | 说明 |
|------|------|
| 置信度分布 | 统计 low/very_low 置信度行数 |
| 员工数偏差 | PDF 员工数 vs Excel 员工数百分比 |
| 未匹配率 | 未匹配员工占比 |
| 金额/工时漂移 | 总金额和总工时的百分比差异 |

### 4.5 核对结论

| 级别 | 条件 |
|------|------|
| pass | 所有仓库通过，无异常 |
| warning | 有差异但金额偏差 < 20% |
| critical | 金额偏差 > 20% 或有严重质量问题 |

---

## 5. 供应商配置说明

### 5.1 内置 Profile（`profiles.py` 中硬编码）

| 供应商 | image_page_policy | 说明 |
|--------|-------------------|------|
| onesource | first_page_only | ONESOURCE 发票，只看首页 |
| fairway | first_page_only | Fairway Staffing |
| osi | first_page_only | OSI Staffing |
| adecco | first_page_only | Adecco Staffing |
| randstad | first_page_only | Randstad Staffing |
| manpower | first_page_only | Manpower Group |
| default | all | 默认 Profile，读所有页 |

### 5.2 动态 Profile（`data/supplier_profiles/` 目录）

- JSON 文件，由系统自动生成
- 包含：`key`, `aliases`, `prompt_notes`, `image_page_policy`, `version`, `failure_count`, `deprecated`
- 优先级高于内置 Profile

### 5.3 字段映射

用户在 Wizard Step 3 中指定 Excel 列名映射：

| 字段 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 员工姓名列 |
| hours | ✅ | 工时列 |
| amount | ✅ | 金额列 |
| employeeId | ❌ | 工号列 |
| currency | ❌ | 币种列 |

映射保存在 `metadata.json` 的 `excelMapping` 字段。

---

## 6. 规则假设说明

### ✅ 明确给过的规则

1. **总金额→仓库→员工逐层下钻**：先核对总金额，有问题再核对明细
2. **低置信度行不阻断**：warning 级别继续流程，进入风险清单
3. **PDF > 2 个时跳过重试**：避免超时
4. **Profile 仅 quality=ok 时生成**：避免垃圾 Profile
5. **Token plan 强制单页**：`_is_token_plan()` 检测 URL 中的 "token-plan"
6. **员工名清洗**：去掉工号（CUE1PK2）、岗位后缀（Forklift Shift）
7. **Excel 行聚合**：同员工多天记录合并 hours/amount

### ⚠️ AI 临时推断的规则

1. **模糊匹配阈值 0.6**：基于测试效果选择，未与业务方确认
2. **自适应容差 1%**：大金额自动放宽，具体阈值未确认
3. **仓库 ID 提取正则**：`DEPT:CA#3` → `3`，覆盖格式有限
4. **表头检测逻辑**：跳过 employee_name 等于列名的行
5. **非员工名过滤列表**：`_NON_EMPLOYEE_NAMES` 硬编码关键词
6. **name 长度过滤**：< 2 或 > 40 字符的行丢弃

---

## 7. 样例数据和测试方式

### 7.1 测试数据

| 数据 | 路径 | 说明 |
|------|------|------|
| SSS 5.11-5.17 | `/Users/zt27532/Documents/报账核对工具/SSS 5.11-5.17/` | 4 个 PDF + 4 个 Excel |
| 内置 fixtures | `tests/test_labor_engine.py` 中硬编码 | 模拟数据，无真实 PDF |

### 7.2 运行测试

```bash
cd "/Users/zt27532/Documents/New project 2"

# 全量测试（111 个，约 2 分钟）
python3 -m pytest tests/test_labor_engine.py tests/test_labor_api.py -x -q

# 只跑引擎测试
python3 -m pytest tests/test_labor_engine.py -x -q

# 只跑 API 测试
python3 -m pytest tests/test_labor_api.py -x -q

# 跑特定测试
python3 -m pytest tests/test_labor_engine.py -k "P2 or P3 or P4" -x -q
```

### 7.3 预期结果

- **111 个测试全部通过**
- 无回归（已有功能不受新改动影响）

### 7.4 手动端到端测试

```bash
# 启动服务
cd "/Users/zt27532/Documents/New project 2"
python3 -m uvicorn bonus_platform.app:app --host 127.0.0.1 --port 8000 --reload

# 浏览器打开
http://127.0.0.1:8000/overseas-labor.html
```

测试步骤：
1. 新建批次（供应商名 "Invoice"，账期 2026-05-11 ~ 2026-05-17，币种 USD）
2. 上传 SSS 5.11-5.17 目录中的 4 个 PDF 和 4 个 Excel
3. 选择 "Employee-expenses-detail" 工作表
4. 映射字段：name=Employee name, hours=Total staff cost accounting time, amount=Total cost
5. 点击「抽取并比对」
6. 等待完成（Token plan 约 20-30 分钟）
7. 检查结果：KPI、比对明细、下载报告

---

## 8. 当前已知问题、风险点、待确认问题

### 🔴 已知问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | **Token plan 抽取极慢** | 高 | `max_pages_per_request=1`，4 PDF 约需 20-30 分钟 |
| 2 | **AI 抽取卡住无超时** | 高 | 后台任务卡住时，30 分钟超时需前端轮询才触发 |
| 3 | **PDF 员工名仍可能失真** | 中 | 部分 PDF 格式特殊，清洗后仍残留工号片段 |
| 4 | **"Open, Open" 未完全过滤** | 中 | 部分变体（如 "Open, Open Open B Bonus Nov"）清洗后仍为 "Open, Open" |
| 5 | **匹配率低** | 中 | SSS 供应商测试匹配率约 60-70%，主要因 PDF 名字 vs Excel 名字格式不同 |

### ⚠️ 风险点

| # | 风险 | 说明 |
|---|------|------|
| 1 | **Profile 污染** | 错误映射跑出的结果可能生成垃圾 Profile，影响后续批次 |
| 2 | **AI 幻觉** | 扫描件 PDF 可能抽取到不存在的员工（已加 expected_rows 约束） |
| 3 | **并发冲突** | 多个批次同时运行可能竞争 AI API 资源 |
| 4 | **数据安全** | PDF/Excel 原始文件存储在本地 outputs/ 目录，无加密 |

### ❓ 待确认问题

| # | 问题 | 说明 |
|---|------|------|
| 1 | **模糊匹配阈值** | 当前 0.6，是否需要调整？ |
| 2 | **金额容差** | 默认 $0.10，大金额 1%，是否符合业务要求？ |
| 3 | **哪些供应商需要 first_page_only** | 内置 Profile 都是 first_page_only，是否正确？ |
| 4 | **Excel 聚合逻辑** | 同员工多天记录合并 hours/amount，是否有其他需要合并的字段？ |
| 5 | **报告格式** | 差异报告 Excel 的 Sheet 结构是否满足业务需求？ |

---

## 9. 下一步建议（按优先级）

### P0 — 必须修复

1. **解决 Token plan 慢的问题**
   - 方案 A：换非 Token plan API（支持多页图片）
   - 方案 B：实现真正的并行抽取（当前 parallel_max_workers=2 但受限于 token plan）
   - 方案 C：优化 prompt 减少 token 消耗

2. **修复 AI 抽取卡住的超时问题**
   - 后台任务应有独立的超时机制，不依赖前端轮询
   - 建议：在 `_perform_labor_extract_compare` 中加 `signal.alarm` 或 `threading.Timer`

3. **提升员工名匹配率**
   - 当前 SSS 供应商匹配率约 60-70%
   - 需要分析未匹配原因：PDF 名字格式 vs Excel 名字格式
   - 可能需要针对 SSS 的 "Last, First" vs "First Last" 格式加转换逻辑

### P1 — 重要改进

4. **增加真实 PDF 测试数据**
   - 当前测试全部用模拟数据，无真实 PDF 文件
   - 建议：将 SSS 5.11-5.17 的 PDF 和 Excel 加入 test fixtures

5. **优化 Profile 自动生成逻辑**
   - 当前 quality=ok 才生成，但多数运行是 warning
   - 建议：quality=warning 且匹配率 > 50% 时也生成

6. **添加 SSS 供应商的内置 Profile**
   - SSS 格式特殊（每员工一页，Last+First 格式）
   - 建议：添加为内置 Profile，设 image_page_policy=all

### P2 — 优化改进

7. **改善前端错误提示**
   - 当前超时只显示"抽取超时"，无具体原因
   - 建议：显示"已处理 X/Y 个 PDF，预计还需 Z 分钟"

8. **添加重跑功能**
   - 当前只能新建批次，不能重跑已有批次
   - 建议：在批次详情页加「重新抽取」按钮

9. **报告格式优化**
   - 当前报告只有一个 Sheet
   - 建议：拆分为多个 Sheet（汇总、员工明细、异常、仓库）

10. **清理 533 个历史运行数据**
    - `outputs/labor_runs/` 有 533 个批次，占用大量磁盘
    - 建议：添加自动清理机制（保留最近 30 天）

---

## 10. 关键代码位置速查

### extract.py（最核心的文件）

| 函数 | 行号 | 说明 |
|------|------|------|
| `extract_invoice_items()` | ~310 | 主入口：规则抽取 + AI 抽取 |
| `_extract_with_ai_text()` | ~790 | 文本模式 AI 抽取 |
| `_extract_with_ai_images()` | ~880 | 图片模式 AI 抽取 |
| `_ai_instruction()` | ~1136 | 生成 AI prompt（含 retry_mode） |
| `_normalize_ai_rows()` | ~1246 | 标准化 + 名字清洗 + 行级过滤 |
| `_clean_employee_name()` | ~1223 | 员工名清洗函数 |
| `_select_invoice_pages()` | ~1504 | 智能页面筛选 |
| `_check_profile_validity()` | ~1490 | Profile 有效性检查 |

### app.py（API 层）

| 函数 | 行号 | 说明 |
|------|------|------|
| `_perform_labor_extract_compare()` | ~460 | 核心比对流程 |
| `_retry_if_better()` | ~723 | 全量重试逻辑 |
| `_retry_low_confidence_rows()` | ~670 | 局部重试逻辑 |
| `_aggregate_excel_rows()` | ~412 | Excel 行聚合 |
| `_build_conclusion()` | ~867 | 核对结论生成 |

### compare.py（比对引擎）

| 函数 | 说明 |
|------|------|
| `compare_labor_items()` | 主比对函数：精确匹配 → 模糊匹配 → 候选推荐 |
| `compare_by_warehouse()` | 仓库维度比对 |
| `_fuzzy_match_employees()` | 模糊匹配算法 |

---

## 11. Git 状态

```
分支: claude/handoff-01

已修改文件:
  bonus_platform/app.py              — API 层（重试、聚合、Profile 生成）
  bonus_platform/config.py           — AI 配置（default_confidence、并行度）
  bonus_platform/engine/labor/extract.py  — 抽取引擎（名字清洗、行级过滤、retry_mode）
  bonus_platform/engine/labor/profiles.py — Profile 管理（动态生成、失效检测）
  bonus_platform/engine/labor/quality.py  — 质量评估（lowConfidenceRows）
  bonus_platform/engine/labor/workbook.py — Excel 解析（表头跳过）
  bonus_platform/static/overseas-labor.html — 前端页面
  bonus_platform/static/overseas-labor.js   — 前端逻辑
  bonus_platform/static/styles.css          — 样式（Notion 风格重构）
  tests/test_labor_engine.py               — 引擎测试（+17 个新测试）
  tests/test_labor_api.py                  — API 测试

新增文件:
  data/supplier_profiles/invoice.json      — 动态 Profile
  data/supplier_profiles/onesource.json    — 动态 Profile
  HANDOFF_OVERSEAS_LABOR_RECONCILIATION.md — 本交接文档
  HANDOFF_AI_OPTIMIZATION.md               — AI 优化交接文档
```

---

*文档结束。如有疑问，请联系原开发者或查阅代码注释。*
