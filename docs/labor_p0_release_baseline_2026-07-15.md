# 海外劳务 P0 发布基线（2026-07-15）

## 目的

在不清理、不重置当前脏工作区的前提下，建立可复现的海外劳务候选验证方式。本文不代表可以部署；P1–P3 闸门仍未完成。

## 当前分支边界

- 当前工作分支包含多项海外劳务范围外的既有提交，不能直接作为海外劳务 release candidate。
- 当前工作区同时存在劳务、FBU、完整 Desktop 和本地生成物改动，禁止 `git add -A`。
- 不得 reset、checkout、删除或覆盖现有用户改动。
- 后续候选应在独立 clean worktree 中从劳务基线提交起步，再迁入经过逐 hunk 审查的海外劳务改动。

## 海外劳务候选路径

运行依赖或发布证据允许进入候选：

- `.env.example`、`.gitignore`、`.vercelignore`、`requirements.txt`、`vercel.json`、`bonus_platform/config.py` 仅迁入劳务相关 hunk，不整文件搬运
- `api/index.py`
- `bonus_platform/app.py` 中逐 hunk 审查的海外劳务代码
- `bonus_platform/engine/labor/**`
- `bonus_platform/worker/**`
- `bonus_platform/static/overseas-labor.html`
- `bonus_platform/static/overseas-labor.js`
- `bonus_platform/static/styles.css`（海外劳务页面实际依赖的共享样式）
- `bonus_platform/static/labor-operations.*`
- `bonus_platform/static/index.html` 的海外劳务入口 hunk
- `bonus_platform/static/assets/workbench-sigma-mark.png`
- `bonus_platform/static/assets/workbench-logo-2026.png`
- `bonus_platform/static/assets/bonus-logo-dark.png`
- `bonus_platform/static/assets/bonus-logo-header-blue.png`
- `data/supplier_profiles/**`
- `docs/labor_*`、`docs/sql/labor_jobs.sql`
- `tools/labor_*`
- `tests/conftest.py` 中客户端契约测试兼容 hunk、`tests/test_labor*`、`tests/test_personal_labor_worker.py` 和劳务相关静态测试 hunk
- `labor-worker-desktop/` 中除依赖、构建和安装产物外的源码
- `.github/workflows/overseas-labor-ci.yml`

明确排除：

- `bonus_platform/engine/fbu_performance/**`
- `desktop/**`
- `.playwright-cli/**`、`.superpowers/**`
- `output/**`、`tmp/**`
- `labor-worker-desktop/node_modules/**`
- `labor-worker-desktop/worker-build/**`
- `labor-worker-desktop/worker-dist/**`
- `labor-worker-desktop/release/**`
- 与海外劳务无关的页面、图片和过程文档

`opendataloader_adapter.py` 及其测试仍属于实验能力；在真实 Golden 证明收益前，不得进入正式运行导入链或 Worker 安装包，也不作为上线证据。

## 运行版本基线

服务启动时计算海外劳务源码指纹。公共 `/api/labor/access` 返回：

- `version=0.5-uat`
- `apiContractVersion=2`
- `buildId`
- `build.status`
- `build.requiredWorkerVersion`

运维鉴权后的 `/api/labor/production-readiness` 才可返回 source ref、进程启动时间和完整源码指纹。`app.py`、`config.py`、`requirements.txt` 属于共享文件，因此无关模块 hunk 也可能触发保守的 `restart_required`；P0 将此视为预期 fail-closed，不是识别故障。

正式 UAT 跨批次复用的全局 Supplier Profile 必须位于发布包内的 `data/supplier_profiles/`。指向项目外或不存在路径的全局覆盖配置会把 build 标记为 `unverified` 并阻断正式操作。经完整审批且处于 active 状态的 run-local Profile 只允许在当前批次内覆盖抽取，并与该批次的 `resultInputFingerprint` 绑定；它不是发布配置，不能跨批次复用，跨批次推广必须在 P2 经 Golden 验证后晋级为发布包 Profile。工作台首页、海外劳务用户页、运维页和 Worker renderer 均不加载任何外部 HTTP(S) runtime；实际依赖的共享样式、关键品牌资产和 Worker 打包入口同时进入源码指纹与必需文件哨兵。

本地源码在服务启动后变化时：

- `build.status=restart_required`
- `runtimeGate.canStartFormalTask=false`
- 页面锁定正式动作
- 受保护写接口返回 `LABOR_SERVICE_RESTART_REQUIRED`
- production-readiness 返回运行版本 blocker
- 正式浏览器写接口无条件校验客户端契约；旧页面或 build 不匹配请求返回 `LABOR_CLIENT_UPGRADE_REQUIRED`，部署环境不能关闭该门禁

`readinessGate.ready=true` 只允许 `status=已生成差异报告` 的员工级正式结果。结果必须同时满足：`batchGuard.allowReleasableReport=true`、`reconciliationDiagnostics.level=ok`、`comparisonSummary.canRelease=true`、`machineCheckStatus=passed` 和结论为 `pass`；PDF/Excel 员工数必须为相同正数，`comparisonRows` 必须逐人完整覆盖且每行 `matchStatus=通过`。只有 `reconciliationScope=total_only_diagnostic` 且 `diagnosticOnly=true` 才被识别为显式诊断批次并禁止进入正式确认；孤立的历史 `total_only_diagnostic` scope 值不降级核对范围，而是继续按员工级要求 fail safe。`待图片识别复核`、失败/运行中状态，以及任一证据缺失或冲突均 fail closed。`extractionQuality=warning` 进入 `needs_review`，`critical` 进入 `blocked`，两者都不能 ready。差异报告记录、下载引用和服务端真实文件必须一致，`sizeBytes` 或 SHA-256 校验失败时不得进入业务确认。

上传文件记录包含内容大小和 SHA-256；本地文件可用时，`resultInputFingerprint` 按当前材料内容、Excel 映射和已生效治理状态重新计算。上传材料、字段映射、reOCR、姓名映射、Profile 或跨仓候选变更后，旧结果立即失效。新任务开始先废止旧正式结果并生成独立 `taskGenerationId`；完成发布同时校验任务代次和任务开始时的输入指纹。较旧任务的进度、失败、结果和 reservation release 都不能修改较新任务。

P0 本地运行时的 metadata 读取、保存、任务状态迁移、Worker 合并和删除使用同一批次进程内锁；任务结果使用代次 + 输入快照 CAS。此机制只解决单进程开发基线，不替代 P1 的 Postgres 多实例事务、revision 和持久化状态机；启用持久化后的跨实例/直接同步竞争仍属于 P1 blocker。

Worker 结果包先完整校验并暂存，全部通过后才原子提交，失败时回滚。缺少、字段不全或输入指纹过期的 metadata 不能与旧通过证据拼接，旧机器结论和报告证据必须失效；正式差异报告声明的 `sizeBytes`、SHA-256 必须与暂存文件逐字节一致。只有同一 `taskGenerationId` 的完整结果写入 accepted marker 后，该 job 才能完成为成功。Worker 也不能覆盖服务端输入文件记录、业务批准、付款或人工复核状态。服务端固定重置为 `businessReviewStatus=pending`、`directPaymentAllowed=false`。Worker 的最低版本在 claim、result 和 complete 三个阶段都重新校验，防止服务升级后旧租约继续提交。

Supplier Profile 别名解析使用词组边界和最长匹配；同等最优候选指向不同 Profile 时回退到未识别家族并要求人工复核，不允许新供应商的宽泛 alias 劫持已有家族。

任何 Vercel runtime，以及明确识别为 `SIGMA_WORKBENCH_HOME=/tmp/...` 且 `SIGMA_LABOR_STORAGE_BACKEND=blob` 的请求作用域组合，在无 Personal Worker 时整批抽取接口固定返回 `LABOR_UAT_EXTRACT_DISABLED`；对象存储选择和 `uat_full` 等旧 access 标记均不例外。同一判定下，本地材料扫描、replay plan、dry-run 和 material-run 创建接口固定返回 `LABOR_LOCAL_MATERIAL_TOOL_DISABLED`。仓库内图像回归 fixture 只保留合成文件标识和聚合金额；真实员工姓名与 OCR 证据原文不进入 Git/CI。

验收或部署环境必须注入：

```bash
SIGMA_LABOR_BUILD_ID=<commit-or-release-id>
SIGMA_LABOR_SOURCE_REF=<branch-or-tag>
SIGMA_LABOR_BUILD_TIME=<UTC-ISO-time>
SIGMA_LABOR_REQUIRED_WORKER_VERSION=0.3.0
```

## 本地验证命令

以下发布签署命令必须在独立 clean candidate worktree 执行。当前脏工作区只能用于开发回归，不可把 `git diff --check` 结果当作候选分支签署证据。

```bash
git diff --check
python3 -m compileall -q bonus_platform/engine/labor bonus_platform/worker
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q \
  tests/test_labor_task_handoff.py tests/test_labor_lifecycle_concurrency.py \
  tests/test_labor_p0_contracts.py tests/test_labor_p0_profiles.py \
  tests/test_labor_hardening.py tests/test_labor_worker_jobs.py \
  tests/test_labor_worker_jobs_postgres.py tests/test_labor_worker_archive.py \
  tests/test_labor_worker_api.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q \
  tests/test_labor*.py tests/test_personal_labor_worker.py tests/test_static_branding.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q
npm --prefix labor-worker-desktop run check
npm --prefix labor-worker-desktop test
```

忽略规则验证：

```bash
git check-ignore -v \
  labor-worker-desktop/node_modules/.package-lock.json \
  labor-worker-desktop/worker-build/pyinstaller-worker/warn-pyinstaller-worker.txt \
  labor-worker-desktop/worker-dist/sigma-labor-worker/sigma-labor-worker \
  labor-worker-desktop/release/latest-mac.yml \
  .playwright-cli/console-2026-07-13T04-49-54-995Z.log \
  .superpowers/brainstorm/.last-token
```

新服务运行验证：

```bash
curl -fsS http://127.0.0.1:${PORT}/api/labor/access \
  | jq '{version,apiContractVersion,buildId,build,runtimeGate}'
```

必须使用独立端口启动候选服务，不停止或复用无法确认版本的现有进程。验证结束后关闭本次启动的进程。

## P0 退出标准

- ADR-002 为唯一当前架构决策，旧 ADR 明确标记 Superseded。
- 正式批次和历史缺省批次均执行员工级核对。
- 页面/API/production-readiness/Worker 任务使用同一版本契约。
- 客户端 build 契约不可由环境变量关闭；Worker 最低版本在领取、上传结果和完成任务时均强制校验。
- 机器通过仍固定 `businessReviewStatus=pending`、`directPaymentAllowed=false`；`canRelease` 不代表业务批准。
- batch guard、reconciliation diagnostics、结论和 readiness 使用同一 fail-closed 放行条件；reOCR 等治理采纳不能直接重写为机器通过。
- 正式结果与材料、Excel 映射及已生效治理状态指纹绑定；输入变更或历史指纹缺失时必须 fail closed。
- 正式结果必须处于严格完成状态，员工数与明细行精确闭合、每行通过，且报告大小和 SHA-256 与服务端文件一致。
- 同批次任务单活；任务代次、输入快照 CAS、metadata/Worker/删除共锁可阻止旧任务或并发操作覆盖新状态。
- 自动生成、审批字段不全或 run-local draft Profile 不得影响正式抽取；已审批 run-local active Profile 只在当前批次内生效并绑定结果指纹，跨批次正式 Profile 必须满足统一审批契约并进入发布包。
- 首轮劳务外部 AI 默认关闭，readiness 对显式启用 fail closed。
- 源码变化可被自动检测并 fail closed。
- 外部/缺失 Profile 路径、关键打包文件缺失和外部 HTTP(S) 页面运行时依赖不能绕过版本冻结。
- 生成物排除规则生效，Worker 源码仍保持可见。
- 新 Supplier Profile 的别名不得劫持旧家族；同等最优歧义必须 fail closed。
- 请求作用域运行时无 Personal Worker 不得执行长任务，本地材料工具不得暴露；隐私 fixture 不得包含真实员工证据。
- 海外劳务 PR CI 配置可解析并覆盖 Python、Worker、路径越界和原始/未知二进制材料检查；scope 不可由手工触发旁路，最终 gate 必须要求 scope/Python/Worker 全部成功。
- 定向、劳务全量、静态和 Worker 测试均有本轮新鲜通过证据。
- 本轮不部署、不写生产密钥、不清理用户文件。

## 2026-07-15 本轮验证证据

- Python 全库回归：`892 passed, 12 skipped, 6 warnings`；海外劳务 CI 等价范围：`828 passed, 6 warnings`；P0 定向并发与交接范围：`135 passed`。警告仅为既有 SWIG deprecation 和 urllib3/LibreSSL 提示。
- Personal Worker：静态检查通过，`9/9` Node 测试通过。
- Python 编译、前端/Worker JavaScript 语法检查、CI YAML 解析和 `git diff --check` 均通过。
- 独立端口新进程返回 `version=0.5-uat`、`apiContractVersion=2`、`buildId=p0-7933d5a7`、`build.status=current`、`requiredWorkerVersion=0.3.0`，且公共 access 不含 source ref 或源码指纹。
- 鉴权 readiness 正确识别本地环境仍缺持久存储、Postgres、Worker 令牌和 Personal Worker 模式，因此返回 `blocked/developer_preflight`；未鉴权 readiness 返回 `401`，没有误报可进入 UAT。
- 真实浏览器通过工作台首页进入海外劳务页面，显示当前 build 与 API v2，“新建核对批次”可用，批次抽屉可正常打开和关闭；页面脚本、样式和图片资源均来自同一独立端口，没有外部 HTTP(S) runtime。
- 缺少客户端版本契约头的正式创建请求返回 `409 / LABOR_CLIENT_UPGRADE_REQUIRED`，且没有创建批次。

以上是当前脏工作区的开发回归证据，不替代独立 clean candidate worktree 的发布签署证据。
