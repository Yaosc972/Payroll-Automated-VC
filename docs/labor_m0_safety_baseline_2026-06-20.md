# 海外劳务工报账核对工具 M0 安全基线

日期：2026-06-20

## 目的

本文件记录继续推进海外劳务工报账核对工具前的安全基线，覆盖当前 Git 状态、测试副作用、真实材料边界、黄金回归起点和下一步准入条件。

本轮不判断生产准确率，不把程序输出当作业务真值，不关闭 P1/P2 风险。

## 当前仓库状态

- 项目目录：`/Users/zt27532/Documents/New project 2`
- 当前分支：`codex/recruitment-bonus-workbench`
- 当前 commit：`f73bbc096c768bd48300d5cc7b13e4d6e9d264a7`

当前分支名仍带有招聘奖金语义，但工作树包含海外劳务、UAT、Blob、黄金回归和测试相关改动。继续推进前应保持模块边界清晰，不应把该分支直接视为干净上线分支。

## 未提交修改清单

已修改文件：

- `.gitignore`
- `bonus_platform/app.py`
- `bonus_platform/engine/labor/report.py`
- `bonus_platform/engine/labor/runs.py`
- `bonus_platform/static/overseas-labor.html`
- `bonus_platform/static/overseas-labor.js`
- `data/supplier_profiles/onesource.json`
- `tests/test_labor_api.py`
- `tests/test_labor_engine.py`
- `tests/test_static_branding.py`
- `vercel.json`

未跟踪文件：

- `bonus_platform/engine/labor/blob_storage.py`
- `bonus_platform/engine/labor/golden.py`
- `docs/labor_golden_regression.md`
- `docs/labor_uat_architecture_adr.md`
- `tests/test_labor_blob_storage.py`
- `tests/test_labor_golden.py`

处理要求：

- 不得 reset、checkout、clean、stash、切分支或覆盖这些改动。
- 编辑上述已有脏文件前，必须先备份对应 diff 到 `/tmp`。
- 新增工作应优先限定在海外劳务模块或文档内。

## 应用启动副作用

只读检查显示：

- `bonus_platform/config.py` 默认输出目录为项目内 `outputs`，`SIGMA_WORKBENCH_HOME` 可覆盖。
- `ensure_data_files()` 会创建输出目录。
- `bonus_platform/app.py` 启动时会调用 `ensure_data_files()`，并会尝试恢复卡住的海外劳务批次状态。
- 海外劳务批次默认写入 `outputs/labor_runs`。
- telemetry 默认写入 `outputs/labor_telemetry/events.jsonl`。
- `bonus_platform/app.py` 仍存在 `run_in_executor` 用于抽取核对任务，不能作为 Vercel Serverless 生产长任务方案。
- `bonus_platform/engine/labor/blob_storage.py` 在 `SIGMA_LABOR_STORAGE_BACKEND=blob` 且存在 `BLOB_READ_WRITE_TOKEN` 时才启用 Blob。

安全结论：

- 本地开发可运行服务，但测试和回放应优先通过 `/tmp` 隔离输出。
- 未设置 Blob token 时，不应访问真实 Blob。
- 不能把当前 Vercel UAT 视作可靠在线抽取环境。

## 安全测试方式

推荐测试环境变量：

```bash
PYTHONDONTWRITEBYTECODE=1
PYTEST_ADDOPTS="-p no:cacheprovider"
```

本轮已验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_golden.py -q
```

结果：

- 退出码：0
- 通过：31
- 失败：0
- 输出目录：测试自身使用 `tmp_path`
- 网络访问：未发现

## 真实材料边界

真实材料目录：

`/Users/zt27532/Documents/报账核对工具`

只读聚合扫描结果：

- PDF：66
- XLSX：11
- HTML：5
- 其他：34

记录原则：

- 不把真实材料复制进仓库。
- 不提交真实材料路径清单。
- 不提交员工姓名、员工号、完整发票号、PDF 原文或 Excel 明细。
- 可以在 `/tmp` 生成本地临时 manifest。
- 可提交 schema、模板、脱敏示例、读取器和合成 fixture。

## 黄金回归起点验证

已存在未跟踪黄金工具：

- `bonus_platform/engine/labor/golden.py`
- `tests/test_labor_golden.py`
- `docs/labor_golden_regression.md`

本轮验证一个候选批次能够只读发现并计算文件哈希，输出到 `/tmp/labor_m0`：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden discover --materials-root /Users/zt27532/Documents/报账核对工具 --batch-key fairway已报账 --output /tmp/labor_m0/fairway_manifest.json
```

结果：

- 退出码：0
- 输出：`/tmp/labor_m0/fairway_manifest.json`
- 网络访问：未发现
- 备注：openpyxl 输出 workbook 默认样式 warning，不影响只读发现。

哈希校验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden validate --manifest /tmp/labor_m0/fairway_manifest.json --materials-root /Users/zt27532/Documents/报账核对工具
```

结果：

- 退出码：0
- batch_count：1
- file_count：7
- errors：0
- warnings：`not_business_approved`
- `require_approved`：false

manifest 聚合检查：

- batch_key：`fairway已报账`
- review_status：`needs_business_review`
- file_count：7
- file_types：`invoice_pdf`, `workbook`
- 所有文件均有 SHA-256。

安全结论：

- 已有工具满足 M0/M1 的起点：只读发现、哈希校验、`/tmp` 输出、业务真值未确认时标记为 `needs_business_review`。
- 该工具尚不等于完整黄金回归；它目前证明的是 manifest 级文件存在性和哈希稳定性，不证明核对结果正确。

## 六类供应商候选覆盖验证

本轮继续验证 M1 的首批供应商覆盖能力。命令输出仍限定在 `/tmp`：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden plan \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --required-suppliers fairway oss osi sss workforce grande \
  --output /tmp/labor_m1/coverage_plan.json
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden prepare \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --required-suppliers fairway oss osi sss workforce grande \
  --output-dir /tmp/labor_m1/manifests \
  --output /tmp/labor_m1/prepare_summary.json
```

结果：

- 候选 manifest 数：6
- 候选 batch 数：6
- 文件总数：45
- 覆盖供应商：fairway、oss、osi、sss、workforce、grande
- 文件类型：`invoice_pdf`、`workbook`
- 所有文件均有 SHA-256。
- 所有候选 batch 的 `expected_result.review_status` 均为 `needs_business_review`。

普通文件和哈希校验：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden validate-dir \
  --manifest-dir /tmp/labor_m1/manifests \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --output /tmp/labor_m1/validate_dir.json
```

结果：

- 退出码：0
- `ok`：true
- `manifest_count`：6
- `batch_count`：6
- `file_count`：45
- `error_count`：0
- `warning_count`：6

发布门禁校验：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden validate-dir \
  --manifest-dir /tmp/labor_m1/manifests \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --require-approved \
  --output /tmp/labor_m1/release_gate.json
```

结果：

- 退出码：1
- `ok`：false
- `manifest_count`：6
- `batch_count`：6
- `file_count`：45
- `error_count`：6
- 每个候选 batch 均因 `expected_not_approved` 被发布门禁拒绝。

安全结论：

- 六类供应商已经能形成候选黄金集。
- 该候选黄金集只证明文件覆盖和哈希稳定，不证明核对结果正确。
- 未经业务审核的 expected result 不会被发布门禁当作通过。

## 脱敏业务审核 handoff 验证

本轮生成六类候选 manifest 的业务审核交接包，输出仍限定在 `/tmp`：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden handoff \
  --manifest-dir /tmp/labor_m1/manifests \
  --output-dir /tmp/labor_m1/business_handoff \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --output /tmp/labor_m1/business_handoff_summary.json
```

结果：

- `ok`：true
- `batch_count`：6
- `file_count`：45
- `needs_business_review_count`：6
- 输出文件：`business_review_template.json`、`BUSINESS_REVIEW_README.md`、`handoff_summary.json`

隐私扫描命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m bonus_platform.engine.labor.golden scan-handoff \
  --handoff-dir /tmp/labor_m1/business_handoff \
  --materials-root /Users/zt27532/Documents/报账核对工具 \
  --output /tmp/labor_m1/business_handoff/privacy_scan.json
```

结果：

- `ok`：true
- `scanned_file_count`：4
- `issue_count`：0

额外文本扫描确认：

- handoff 模板中 `review_items` 数：6
- handoff 模板不含 `batch_key`
- handoff 模板不含 `supplier_ref`
- handoff 模板使用 `review_batch_ref` 作为脱敏批次引用。
- 未发现材料根路径、真实批次名、PDF/XLSX 文件名、员工号形态、Blob token 形态。

安全结论：

- 业务审核 handoff 已可用于收集 expected metrics，但仍不是已审核黄金集。
- 业务 reviewer 返回前，所有批次仍保持 `needs_business_review`。
- handoff 包不应提交到 Git；如需分享，应先重新运行隐私扫描。

## 脱敏审核返回流程验证

本轮补齐 reviewer 返回脱敏模板后的本地处理流程，目标是避免业务审核交接包回流后重新依赖真实批次名或真实供应商名。

变更范围：

- `bonus_platform/engine/labor/golden.py`
- `tests/test_labor_golden.py`
- `docs/labor_golden_regression.md`

新增能力：

- `validate-review` 支持 `--review-batch-ref`。
- `apply-review` 支持 `--review-batch-ref`。
- `validate_golden_review_template(...)` 支持按 `review_batch_ref` 过滤。
- `apply_golden_review_template(...)` 支持按 `review_batch_ref` 应用 reviewed manifest copy。
- 文档新增 `Returned Redacted Review Workflow`，明确 returned handoff 先隐私扫描，再 `validate-review`，再 `apply-review`，最后 `validate-dir --require-approved`。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_golden.py::test_golden_regression_doc_includes_redacted_review_return_workflow tests/test_labor_golden.py::test_validate_golden_review_template_can_filter_to_one_redacted_review_batch_ref tests/test_labor_golden.py::test_validate_golden_review_template_rejects_missing_redacted_review_batch_ref tests/test_labor_golden.py::test_apply_review_template_accepts_redacted_handoff_review_batch_ref -q
```

结果：4 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_golden.py -q
```

结果：35 passed。

CLI 参数检查：

- `python3 -m bonus_platform.engine.labor.golden validate-review --help` 已显示 `--review-batch-ref`。
- `python3 -m bonus_platform.engine.labor.golden apply-review --help` 已显示 `--review-batch-ref`。

数据保护结论：

- 未读取真实材料内容。
- 未向真实材料目录写入。
- 未向 `outputs/labor_runs` 写入。
- 未访问 Blob/UAT。
- 返回流程继续要求 handoff 目录在 `/tmp` 或 ignored local directory 中处理，不提交 Git。

## M2 失败语义检查：抽取失败不得显示通过

本轮验证业务 HTML 报告的失败语义：当结构化结果表明抽取或解析失败时，即使金额差额为 0、明细为空，也不得展示“通过”或“核对通过”。

变更范围：

- `bonus_platform/engine/labor/report.py`
- `tests/test_labor_engine.py`

新增行为：

- `build_labor_business_html_report(...)` 的业务结论判断新增以下失败信号：
  - `summary.systemIncomplete`
  - `summary.extractionFailed`
  - `summary.failed`
  - `summary.status in {"抽取失败", "解析失败", "核对失败"}`
- 命中失败信号时，首屏结论显示“系统未能完成核对”。
- 失败报告提示业务用户“请人工查看原发票和账单后重新生成报告”，不输出技术堆栈或内部字段。

TDD 记录：

- 先新增 `test_build_labor_business_html_report_does_not_pass_when_extraction_failed`。
- RED 结果：测试失败，报告未包含“系统未能完成核对”，说明旧逻辑会漏判 `extractionFailed`。
- GREEN 后结果：相关业务报告测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_engine.py::test_build_labor_business_html_report_does_not_pass_when_extraction_failed tests/test_labor_engine.py::test_build_labor_business_html_report_uses_business_language_without_internal_terms -q
```

结果：2 passed。

数据保护结论：

- 使用合成 summary 和空 rows。
- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。

## M2 失败语义检查：有总额/人数但无员工明细不得显示通过

本轮继续验证业务 HTML 报告的空明细风险：当 summary 已有 PDF/Excel 总额或员工数，但 `rows` 为空时，不能仅因为总差额为 0 就展示“通过”。这类状态说明员工级核对没有完成，业务报告应提示系统未能完成核对。

变更范围：

- `bonus_platform/engine/labor/report.py`
- `tests/test_labor_engine.py`

新增行为：

- 当 `rows` 为空，且以下任一 summary 字段非 0 时，`build_labor_business_html_report(...)` 首屏结论为“系统未能完成核对”：
  - `pdfEmployeeCount`
  - `excelEmployeeCount`
  - `pdfAmountTotal`
  - `excelAmountTotal`
- 该规则避免将“只有总额、没有员工级明细”的不完整核对误标为通过。

TDD 记录：

- 先新增 `test_build_labor_business_html_report_does_not_pass_when_detail_rows_are_missing`。
- RED 结果：测试失败，旧逻辑未包含“系统未能完成核对”，说明空明细且总额一致会漏判为通过。
- GREEN 后结果：相关业务报告测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_engine.py::test_build_labor_business_html_report_does_not_pass_when_detail_rows_are_missing tests/test_labor_engine.py::test_build_labor_business_html_report_does_not_pass_when_extraction_failed tests/test_labor_engine.py::test_build_labor_business_html_report_uses_business_language_without_internal_terms -q
```

结果：3 passed。

数据保护结论：

- 使用合成 summary 和空 rows。
- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。

## M2 前端错误语义：请求错误转业务下一步

本轮验证前端请求错误语义，目标是避免业务用户看到原始技术错误后无法判断下一步。覆盖场景：

- 批次不存在 / run not found。
- 上传文件、文件保存或持久化相关失败。
- 网络或服务连接失败。

变更范围：

- `bonus_platform/static/overseas-labor.js`
- `tests/test_static_branding.py`

新增行为：

- `requestJson(...)` 对 HTTP 错误调用 `formatLaborRequestError(...)`。
- 批次丢失类错误显示“本批次记录未找到”，并提示重新创建批次、重新上传材料，以及确认当前环境是否支持持久化保存。
- 上传或文件保存类错误显示“上传文件未保存成功”，并提示重新上传 PDF 发票和 Excel 账单。
- 连接失败类错误显示“无法连接当前服务”，并提示确认本地服务或联系管理员检查环境状态。

TDD 记录：

- 先新增 `test_overseas_labor_frontend_maps_technical_request_errors_to_business_next_steps`。
- RED 结果：测试失败，`overseas-labor.js` 缺少 `formatLaborRequestError`。
- GREEN 后结果：前端错误语义测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_static_branding.py::test_overseas_labor_frontend_maps_technical_request_errors_to_business_next_steps tests/test_static_branding.py::test_overseas_labor_frontend_blocks_vercel_light_uat_extract -q
```

结果：2 passed。

```bash
node --check bonus_platform/static/overseas-labor.js
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。

## M2 后端结构化错误语义

本轮目标：

- 将上传/抽取关键失败从裸字符串错误升级为结构化业务错误。
- 让前端兼容 `detail` 对象，避免显示 `[object Object]`。
- 保持业务用户看到的提示为“下一步该怎么做”，不暴露技术栈细节。

变更范围：

- `bonus_platform/app.py`
- `bonus_platform/static/overseas-labor.js`
- `tests/test_labor_api.py`
- `tests/test_static_branding.py`

新增行为：

- 后端新增 `_labor_request_error(...)`，统一返回：
  - `message`
  - `errorCode`
  - `retryable`
  - `requiresReupload`
  - `requiresHumanReview`
  - `nextAction`
- 批次不存在返回 `LABOR_RUN_NOT_FOUND`，提示重新创建批次并上传材料。
- Vercel UAT 正式抽取阻断返回 `LABOR_UAT_EXTRACT_DISABLED`，提示使用测试材料验证或本地/内网持久化环境。
- 抽取前置条件缺失返回结构化错误：
  - `LABOR_MAPPING_REQUIRED`
  - `LABOR_PDF_REQUIRED`
- 前端 `formatLaborRequestError(...)` 支持读取 `detail.message` 和 `detail.nextAction`。

TDD 记录：

- 先新增 `test_labor_extract_vercel_uat_light_mode_returns_structured_next_action`。
- 先新增 `test_labor_upload_missing_run_returns_structured_next_action`。
- 先新增静态断言，要求前端读取 `message?.message` 和 `message?.nextAction`。
- RED 结果：后端测试失败，原因是 `detail` 仍为字符串；前端测试失败，原因是未读取结构化字段。
- GREEN 后结果：后端和前端结构化错误语义测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_extract_is_blocked_in_vercel_uat_light_mode tests/test_labor_api.py::test_labor_extract_vercel_uat_light_mode_returns_structured_next_action tests/test_labor_api.py::test_labor_upload_missing_run_returns_structured_next_action
```

结果：3 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_static_branding.py::test_overseas_labor_frontend_maps_technical_request_errors_to_business_next_steps
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_run_api_creates_batch_uploads_files_and_suggests_mapping tests/test_labor_api.py::test_labor_compare_records_failure_when_pdf_extraction_returns_no_employee_rows tests/test_labor_api.py::test_labor_recover_stuck_run_marks_retryable_system_interruption tests/test_labor_api.py::test_labor_extract_is_blocked_in_vercel_uat_light_mode tests/test_labor_api.py::test_labor_extract_vercel_uat_light_mode_returns_structured_next_action tests/test_labor_api.py::test_labor_upload_missing_run_returns_structured_next_action
```

结果：6 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_static_branding.py::test_overseas_labor_frontend_blocks_vercel_light_uat_extract tests/test_static_branding.py::test_overseas_labor_frontend_maps_technical_request_errors_to_business_next_steps tests/test_static_branding.py::test_overseas_labor_download_prefers_business_report_for_business_users
```

结果：3 passed。

```bash
node --check bonus_platform/static/overseas-labor.js
```

结果：通过。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/app.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 `/tmp/labor_m2_backend_error_semantics_prechange.diff` 作为脏文件修改前 diff 备份。

## M2 Blob 跨请求恢复路径 materialize

本轮目标：

- 验证并修复 Blob 恢复批次时 metadata 文件路径仍为相对路径的问题。
- 确保跨实例/跨请求恢复后，`metadata.json` 中的报告文件引用指向本地已恢复文件。
- 不访问真实 Blob，不读取真实材料。

变更范围：

- `bonus_platform/engine/labor/blob_storage.py`
- `tests/test_labor_blob_storage.py`

新增行为：

- `sync_labor_run_from_blob(...)` 在下载并写回所有 Blob 文件后，会 materialize `metadata.json`。
- `metadata.json` 中 `files.*.path` 从 Blob 中的相对路径恢复为本地绝对路径。
- 使用临时文件写入并通过 `os.replace(...)` 原子替换，避免半写入 metadata。

TDD 记录：

- 先新增 `test_sync_labor_run_from_blob_materializes_metadata_file_paths`。
- RED 结果：测试失败，原因是恢复后的 `metadata.json` 仍保留 `reports/business.html` 等相对路径。
- GREEN 后结果：Blob 恢复测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py::test_sync_labor_run_from_blob_materializes_metadata_file_paths
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py
```

结果：8 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches
```

结果：10 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/engine/labor/blob_storage.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录和 `/tmp/labor_m2_blob_materialize_prechange.diff` 作为修改前 diff 备份。

## M2 Blob 端到端隔离回归

本轮目标：

- 模拟“本地 run_dir 同步到 Blob、换实例恢复、继续读取业务报告/差异报告”的核心持久化链路。
- 验证写入 Blob 的 `metadata.json` 不携带当前实例的绝对路径。
- 继续使用 fake Blob，不访问真实 UAT/Blob。

变更范围：

- `bonus_platform/engine/labor/blob_storage.py`
- `tests/test_labor_blob_storage.py`

新增行为：

- `sync_labor_run_to_blob(...)` 上传 `metadata.json` 前会先 canonicalize metadata。
- Blob 中保存的 metadata 文件路径保持为 run 目录内相对路径。
- `sync_labor_run_from_blob(...)` 恢复到任意新 run_dir 后，会将 metadata 文件路径 materialize 到新 run_dir。

TDD 记录：

- 先新增 `test_labor_blob_sync_roundtrip_restores_reports_with_current_run_dir`。
- RED 结果：测试失败，恢复后的 business report 路径仍指向 source run_dir。
- GREEN 后结果：roundtrip 测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py::test_labor_blob_sync_roundtrip_restores_reports_with_current_run_dir
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py
```

结果：9 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches tests/test_labor_api.py::test_labor_extract_is_blocked_in_vercel_uat_light_mode tests/test_labor_api.py::test_labor_upload_missing_run_returns_structured_next_action
```

结果：13 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/engine/labor/blob_storage.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录和 `/tmp/labor_m2_blob_roundtrip_prechange.diff` 作为修改前 diff 备份。

## M2 下载接口跨请求恢复

本轮目标：

- 验证本地报告文件缺失、Blob 可恢复时，业务报告下载接口可以恢复并返回文件。
- 覆盖报告恢复在子目录但下载 URL 只有 basename 的场景。
- 继续使用 fake Blob，不访问真实 UAT/Blob。

变更范围：

- `bonus_platform/app.py`
- `tests/test_labor_api.py`

新增行为：

- `/api/labor/runs/{run_id}/download/{filename}` 在根目录找不到文件时，会先触发 Blob 恢复。
- 恢复后如果 `run_dir / filename` 仍不存在，会读取 metadata 的 `files.*.filename/path`，按文件名反查实际路径。
- 支持 `files.businessReport.path` 等子目录报告路径，例如 `reports/business.html`。

TDD 记录：

- 先新增 `test_labor_download_recovers_nested_blob_report_by_metadata`。
- RED 结果：测试失败，接口返回 404；原因是下载接口只检查 `run_dir / business.html`，没有按 metadata 查找 `reports/business.html`。
- GREEN 后结果：下载接口恢复测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_download_recovers_nested_blob_report_by_metadata
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_download_recovers_nested_blob_report_by_metadata tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches
```

结果：12 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/app.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录和 `/tmp/labor_m2_download_recover_prechange.diff` 作为修改前 diff 备份。

## M2 下载恢复失败语义

本轮目标：

- 验证下载接口在本地报告文件缺失、Blob 恢复失败时返回结构化业务错误。
- 避免业务用户只看到普通 404，无法判断是报告不存在还是持久化恢复失败。
- 继续使用 fake Blob，不访问真实 UAT/Blob。

关联问题：

- `LAB-P1-002`：报告持久化和跨请求恢复仍需验证。
- `LAB-P2-003`：失败时必须给出可理解的阶段、下一步和错误编号。

变更范围：

- `bonus_platform/app.py`
- `tests/test_labor_api.py`

新增行为：

- `/api/labor/runs/{run_id}/download/{filename}` 在本地找不到文件且 Blob 恢复返回失败或抛错时，返回 HTTP 503。
- 错误体使用结构化 `detail`：
  - `errorCode`: `LABOR_REPORT_RESTORE_FAILED`
  - `retryable`: `true`
  - `requiresReupload`: `false`
  - `nextAction`: 提示稍后重试或联系管理员检查文件持久化状态
- 错误体不包含本地路径、Blob 路径或内部堆栈。

TDD 记录：

- 先新增 `test_labor_download_returns_structured_restore_failure_when_blob_sync_fails`。
- RED 结果：测试失败，接口返回 404；原因是下载接口忽略 Blob 恢复返回值，最终落入普通“文件不存在或已被清理”。
- GREEN 后结果：下载接口恢复失败测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_download_returns_structured_restore_failure_when_blob_sync_fails
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_download_recovers_nested_blob_report_by_metadata tests/test_labor_api.py::test_labor_download_returns_structured_restore_failure_when_blob_sync_fails tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches
```

结果：13 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/app.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录、`/tmp/labor_pycache` 和 `/tmp/labor_m2_download_structured_error_prechange.diff` 作为修改前 diff 备份。

## M2 下载文件缺失语义

本轮目标：

- 验证下载接口在报告文件确实不存在或已被清理时，返回结构化业务错误。
- 避免前端或业务用户收到裸字符串 `文件不存在或已被清理。`，无法判断下一步。
- 不访问真实 UAT/Blob，不读取真实材料。

关联问题：

- `LAB-P2-003`：失败时必须给出可理解的阶段、下一步和错误编号。

变更范围：

- `bonus_platform/app.py`
- `tests/test_labor_api.py`

新增行为：

- `/api/labor/runs/{run_id}/download/{filename}` 在无法找到报告且不是 Blob 恢复失败时，返回 HTTP 404。
- 错误体使用结构化 `detail`：
  - `errorCode`: `LABOR_REPORT_FILE_MISSING`
  - `retryable`: `false`
  - `requiresReupload`: `false`
  - `requiresHumanReview`: `true`
  - `nextAction`: 提示重新生成报告或联系管理员恢复批次报告
- 错误体不包含本地路径或内部堆栈。

TDD 记录：

- 先新增 `test_labor_download_returns_structured_missing_file_error`。
- RED 结果：测试失败，接口返回字符串 detail，无法读取 `errorCode`。
- GREEN 后结果：下载文件缺失测试通过。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_download_returns_structured_missing_file_error
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_download_recovers_nested_blob_report_by_metadata tests/test_labor_api.py::test_labor_download_returns_structured_restore_failure_when_blob_sync_fails tests/test_labor_api.py::test_labor_download_returns_structured_missing_file_error tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches
```

结果：14 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/app.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录、`/tmp/labor_pycache` 和 `/tmp/labor_m2_download_missing_structured_prechange.diff` 作为修改前 diff 备份。

## M2 下载恢复异常脱敏覆盖

本轮目标：

- 验证 Blob 恢复报告时若底层同步函数抛出异常，API 响应不会泄露异常文本、本地路径或敏感 token。
- 将该行为纳入自动化回归，防止后续改动把内部错误直接暴露给业务用户。
- 不访问真实 UAT/Blob，不读取真实材料。

关联问题：

- `LAB-P1-002`：报告持久化和跨请求恢复仍需验证。
- `LAB-P2-003`：失败时不得暴露内部堆栈、路径或密钥。

变更范围：

- `tests/test_labor_api.py`
- 本轮未修改生产实现；当前 `bonus_platform/app.py` 已捕获恢复异常并返回结构化 `LABOR_REPORT_RESTORE_FAILED`。

新增覆盖：

- `sync_labor_run_from_blob` 抛出含 token 和本地路径的异常时，下载接口返回 HTTP 503。
- 响应体仍为结构化 `LABOR_REPORT_RESTORE_FAILED`。
- 响应体不包含异常中的 token、本地报告路径或 run_dir。

TDD 记录：

- 新增 `test_labor_download_masks_blob_restore_exception_details`。
- 结果：测试首次运行即通过，说明上一轮下载恢复失败实现已经覆盖该异常分支；本轮作为回归覆盖保留。

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_api.py::test_labor_download_masks_blob_restore_exception_details
```

结果：1 passed。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python3 -m pytest tests/test_labor_blob_storage.py tests/test_labor_api.py::test_labor_download_recovers_nested_blob_report_by_metadata tests/test_labor_api.py::test_labor_download_returns_structured_restore_failure_when_blob_sync_fails tests/test_labor_api.py::test_labor_download_masks_blob_restore_exception_details tests/test_labor_api.py::test_labor_download_returns_structured_missing_file_error tests/test_labor_api.py::test_labor_readiness_gate_blocks_when_report_file_is_missing tests/test_labor_api.py::test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches
```

结果：15 passed。

```bash
PYTHONPYCACHEPREFIX=/tmp/labor_pycache python3 -m py_compile bonus_platform/app.py
```

结果：通过。

数据保护结论：

- 未读取真实材料内容。
- 未写入真实材料目录。
- 未访问 Blob/UAT。
- 未写入 `outputs/labor_runs`。
- 仅写入 pytest 临时目录、`/tmp/labor_pycache` 和 `/tmp/labor_m2_download_restore_exception_prechange.diff` 作为修改前 diff 备份。

## 输出目录检查

本轮测试和发现命令输出：

- `/tmp/labor_m0/fairway_manifest.json`
- `/tmp/labor_m1/coverage_plan.json`
- `/tmp/labor_m1/prepare_summary.json`
- `/tmp/labor_m1/validate_dir.json`
- `/tmp/labor_m1/release_gate.json`
- `/tmp/labor_m1/manifests/*_manifest.json`
- `/tmp/labor_m1/business_handoff/*`
- `/tmp/labor_m1/business_handoff_summary.json`

本轮未向以下位置写入新运行结果：

- `outputs/labor_runs`
- 真实材料目录
- Blob/UAT

## 当前风险登记

- LAB-P1-001 未关闭：仍存在进程内 `run_in_executor`，不能作为 Vercel Serverless 生产长任务方案。
- LAB-P1-002 未关闭：Blob 持久化相关代码存在，但仍需隔离测试和跨请求一致性验证。
- LAB-P1-003 部分起步：已有黄金 manifest 工具和测试，但六类供应商黄金批次尚未全部经过业务审核。
- LAB-P2-001 未关闭：历史 `outputs/labor_runs` 不能作为准确率依据。
- LAB-P2-002 部分缓解：业务报告和高级复核折叠已开始推进，但业务主流程仍需继续收口。
- LAB-P2-003 未关闭：失败语义和业务化错误恢复仍需系统测试。

## 下一步准入建议

优先顺序：

1. 将 `golden.py`、`tests/test_labor_golden.py`、`docs/labor_golden_regression.md` 的未跟踪黄金体系纳入受控改动范围，并继续只用 `/tmp` 输出。
2. 把业务 reviewer 返回的 handoff 模板接入 `validate-review` / `apply-review` 流程，仅在 reviewed fields 完整时生成 reviewed manifest。
3. 增加 M0/M1 回归命令文档，明确哪些命令不会写入 `outputs/labor_runs`、Blob 或真实材料目录。

## 本轮结论

M0 安全基线已建立到可继续推进的程度，但整体 Goal 远未完成。

当前状态：PASS WITH OPEN RISKS
