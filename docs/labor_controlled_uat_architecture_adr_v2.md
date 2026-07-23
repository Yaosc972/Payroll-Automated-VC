# ADR-002：海外劳务报账核对受控 UAT 架构

状态：Accepted
决策日期：2026-07-15
目标环境：`controlled-uat-macos`
替代：`docs/labor_uat_architecture_adr.md`

## 决策摘要

首轮上线采用 Personal Worker 架构：

- Vercel 只承担身份、批次、字段映射、人工复核、状态查询和短 API。
- Postgres 是批次状态、任务队列、租约、业务复核状态和审计索引的唯一事实来源。
- P1 采用经数据所有者、地域和权限审批的 Private Supabase Storage 保存内容寻址输入、版本化结果清单、归档 metadata 快照和报告；保留期内不得覆盖，可按批准的删除策略清除。现有 Vercel Blob 适配器不具备本阶段要求的私有短期签名直传/直下能力，只保留为非 P1 兼容路径。
- 耗时解析、PDF 渲染、本机 OCR 和报告生成只在当前用户绑定的 Personal Worker 执行。
- Vercel Function 不代理真实大文件，也不执行整批长任务。

本阶段只开放受控人工复核 UAT。所有批次始终满足：

- `manualReviewRequired=true`
- `directPaymentAllowed=false`

## 上线 Goal

先向 1–2 名管理员开放影子 UAT，完成 30 批真实材料验证后，再向 3–5 名指定薪酬人员开放受控 UAT。两阶段都必须达到：

1. 用户只能访问和处理自己的批次。
2. 批次可恢复、可重试、可审计，不依赖单个 Vercel 进程或本机临时目录。
3. 已验证文档家族可复用版本化规则；未知供应商正确识别或明确阻断。
4. 每个输入文件、页面、员工明细和报告都有来源、版本和处理状态。
5. 机器结果必须经过业务人员显式复核，不能直接转成付款结论。

## 非目标

- 无人值守自动批准或直接付款。
- 宣称任意未知供应商都能自动识别。
- 首轮 Windows 正式发布。
- 首轮真实材料调用外部 AI/OCR 服务。
- 将 Worker 重新合并进完整 Sigma Desktop。

## 核对范围与结论语义

### 正式批次

所有正式批次必须持久化：

```text
reconciliationScope=employee_detail_required
```

缺少该字段的历史批次也按员工级核对处理。总额一致不能跳过员工金额、工时、姓名和仓库归属核对。

只有同时满足 `reconciliationScope=total_only_diagnostic` 和 `diagnosticOnly=true` 的任务才视为显式内部诊断任务。它不能生成正式业务报告、机器通过、业务批准或付款结论。仅遗留了 `total_only_diagnostic` scope 值、但没有显式诊断标记的历史批次不得降级核对范围，继续按员工级要求 fail safe。

### 三层状态

平台统一使用三层语义，禁止用“可上线”混写：

1. `machineCheckStatus=passed|needs_review|blocked`：机器证据门禁状态。
2. 引擎完成后固定 `businessReviewStatus=pending`；有权限的业务人员显式确认后才变为 `approved|rejected`。
3. `directPaymentAllowed`：本阶段固定为 `false`。

环境政策 `manualReviewRequired=true` 始终不变；只有 `businessReviewStatus=approved` 后，结果级 `requiresHumanReview` 才可变为 `false`。现有 `canRelease` 只是 API v2 兼容别名，含义仅为“机器证据允许进入业务确认”，不得驱动“可上线”文案或按钮；API v3 删除该字段。

机器通过必须由服务端统一判定。只有 `status=已生成差异报告` 的员工级正式结果，且同时满足 `batchGuard.allowReleasableReport=true`、`reconciliationDiagnostics.level=ok`、`machineCheckStatus=passed`、`canRelease=true` 和结论为 `pass` 才能进入业务确认。PDF/Excel 员工数必须为相同正数，`comparisonRows` 必须逐人完整覆盖且每行通过；差异报告记录、下载引用、真实文件、`sizeBytes` 和 SHA-256 必须一致。显式诊断批次、`待图片识别复核`、失败/运行中或任一字段缺失/冲突均 fail closed；`extractionQuality=warning` 对应 `needs_review`，`critical` 对应 `blocked`，两者都不能进入 ready。

正式结果必须携带 `resultInputFingerprint`，并与当前材料、Excel 映射和已生效治理状态一致。上传材料、字段映射、reOCR、姓名映射、Profile 或跨仓候选变更后旧结果必须立即失效并整批重新核对，不能直接重写正式通过状态。每次任务生成独立 `taskGenerationId`；结果发布同时校验任务代次和输入快照。旧任务的进度、失败、结果及资源释放不能修改较新任务。Worker 结果归档不能提交业务批准、付款或免人工复核字段；即使归档不含 metadata，服务端也必须重置业务复核。

## 新供应商准入

准入单位是“文档家族 + 适配器/Profile 版本”，不是供应商名称。新材料先识别文档家族，再决定处理方式：

1. 已有文档家族：直接复用已验证家族能力；只有出现供应商特有差异时才新增版本化 Supplier Profile。
2. 新文档家族：新增独立适配器，并附业务批准 Golden 后才能启用。
3. 证据不足：进入人工复核，不通过新增宽松正则强行识别。

任何未验证文档家族、适配器或实际启用的 Profile 版本，以及未闭合文件、币种冲突、仓库不明或员工明细缺失，都不得获得机器通过状态。

## 数据流

1. 浏览器从服务端取得当前用户和批次权限。
2. 浏览器使用短期授权把 PDF/Excel 直接上传到私有对象存储。
3. API 在 Postgres 中创建带 owner、幂等键和版本号的任务。
4. 当前用户绑定的 Worker 通过认证 API 领取任务，由 API 在 Postgres 中原子 claim，并返回任务范围内短期文件地址。
5. Worker 下载材料、校验 SHA-256、运行解析/OCR/核对并持续心跳。
6. Worker 把报告和结果清单直传对象存储；API 校验清单、哈希和任务租约后提交状态。
7. 页面展示机器结果并要求业务人员逐项确认；复核事件写入耐久审计。

对象存储中的版本化 `metadata.json` 只能作为归档快照，不能参与并发状态决策。

P0 本地开发运行时采用每批次进程内锁、单活 reservation token、任务代次和结果发布 CAS，串行化普通 metadata 读写、任务状态迁移、Worker 归档和删除。Worker ZIP 必须先完整校验和暂存，再原子提交并可回滚；缺少、部分或过期 metadata 不得沿用旧机器证据。正式报告的大小和哈希必须与暂存文件一致，且只有同代完整结果写入 accepted marker 后，Worker job 才能完成为成功。该机制仅提供单进程过渡保护，不构成跨实例或持久化一致性；P1 必须由 Postgres 事务、revision/幂等键和对象存储清单取代。

## 身份、设备和 owner

- owner 必须来自服务端认证上下文，客户端不得指定或覆盖。
- 所有批次、文件、映射、治理、任务和下载接口必须重复校验 owner 或管理员权限。
- Worker 令牌必须短期有效、绑定用户和设备、可轮换、可吊销。
- 静态环境变量 Token 只允许开发 E2E，不满足受控 UAT 身份要求。
- Worker 不持有数据库、对象存储或外部 AI 主密钥。

## OCR、外部 AI 与隐私

首轮受控 UAT 固定 `SIGMA_LABOR_EXTERNAL_AI_ENABLED=false`，只使用确定性解析和本机 OCR。真实材料不得发送到外部模型；本机能力无法闭合时进入人工复核。

外部 AI 只有在处理地域、数据范围、留存、脱敏、日志和法务依据获得书面批准后才能另行启用。输出始终只是候选证据，必须经过逐文件金额闭合和人工确认。

## 运行版本契约

页面与 API 使用以下运行身份。公共 access 只返回短 build ID、模块/API 版本、状态和最低 Worker 版本；完整 source ref、启动时间和源码指纹仅在运维鉴权后的 readiness/operations 中返回：

- 模块版本：`0.5-uat`
- API 契约版本：`2`
- build/revision
- source ref
- 进程启动时间
- 启动源码指纹与当前源码指纹
- 最低 Worker 版本

进程启动后任一海外劳务核心源码、Worker 源码、页面或运行配置变化时，运行状态变为 `restart_required`：

- 页面继续允许查看，但锁定新建、上传、映射和启动核对。
- 正式写操作返回 `LABOR_SERVICE_RESTART_REQUIRED`。
- `production-readiness` 必须加入运行版本阻断项。

跨批次复用的正式 Supplier Profile 只能来自 release bundle 内的 `data/supplier_profiles/`，且必须满足审批契约；项目外或不存在的全局 Profile 路径使 build 变为 `unverified`。经完整审批的 run-local active Profile 可以仅对当前批次生效并与输入指纹绑定，但不构成跨批次发布配置；跨批次推广必须在 P2 经 Golden 验证后晋级到 release bundle。Profile 别名解析使用词组边界和最长匹配，同等最优候选指向不同 Profile 时 fail closed，防止新供应商宽泛 alias 劫持已有家族。工作台首页、海外劳务用户页、运维页和 Worker renderer 不依赖任何外部 HTTP(S) runtime；共享样式、关键图片资产和 Worker 直接打包依赖同时纳入指纹与必需文件哨兵。

正式浏览器写接口无条件校验页面/API/build 契约，部署环境不得关闭。Worker 在 claim、result 和 complete 阶段均校验 `x-worker-version` 不低于任务要求与当前最低版本两者的较高值；服务升级后旧 Worker 不得凭既有租约继续提交。

任何 Vercel runtime，以及明确识别为 `SIGMA_WORKBENCH_HOME=/tmp/...` 且 `SIGMA_LABOR_STORAGE_BACKEND=blob` 的请求作用域组合，在无 Personal Worker 时必须拒绝整批抽取长任务，不得因对象存储选型或 `uat_full` 等旧 access 标记改走同步路径。同一判定下，本地材料扫描、replay plan、dry-run 和 material-run 创建接口必须返回 `LABOR_LOCAL_MATERIAL_TOOL_DISABLED`。仓库中的图像回归 fixture 只允许合成标识和聚合数据，不保存真实员工姓名或 OCR 证据原文。

API v2 中保留的 `runtimeGate.canStartFormalTask` 仅是运行源码一致性的兼容别名，不代表存储、身份、Worker 或 Golden 已达到受控 UAT readiness；新页面使用 `runtimeSourceCurrent`。

部署环境必须注入真实 commit/release ID；`local-worktree` 或无法确认的 build 不得作为最终验收证据。

## readiness 与发布闸门

当前 P0 `/api/labor/production-readiness` 仅为 `developer_preflight`，即使配置项齐全也最多返回 `ready_for_developer_preview`，不构成开放真实材料的充分证据。

P1–P3 完成自动检查后，正式上传和任务提交必须服务端强制检查同一 readiness。以下条件全部满足时可返回 `ready_for_shadow_uat`，仅允许管理员和指定影子试点人员处理真实材料：

1. 真实身份、角色和 owner 隔离有效。
2. Postgres 状态、任务、租约和审计可用。
3. Private Supabase Storage 可写、可读、可删，浏览器输入与业务报告使用短期签名直传直下。
4. 在线 Worker 身份、设备、版本和所需 OCR 能力符合要求。
5. Worker 安装包签名、升级清单和哈希验证有效。
6. 运行 build 为 `current`，页面/API/Worker 版本相容。
7. 业务批准 Golden 通过真实 HTTP + Storage + Postgres + Worker 全链路。
8. 返回值仍为 `manualReviewRequired=true`、`directPaymentAllowed=false`。

影子 UAT 完成下方 30 批退出闸门后，才可返回 `ready_for_controlled_uat` 并扩大到 3–5 名正式 UAT 用户。测试材料验证可以独立保留，但不能绕过正式材料闸门。

## Golden 验收

- Golden 必须包含业务批准真值，而不仅是文件存在和哈希。
- 每个文档家族至少覆盖正常、边界和应阻断样本。
- 任一关键文件出现错误放行、错误金额、员工漏抽、币种误判或跨用户访问，整次发布失败。
- 单文件严重错误不能被批次平均覆盖率抵消。
- P4 影子 UAT 退出闸门要求至少完成 30 个真实批次，覆盖现有家族和至少两个新供应商；要求零错误放行、零越权、零任务丢失。该条件不作为首批管理员影子验证的循环前置条件。

## Worker 首轮边界

- 首轮只承诺 macOS Apple Silicon。
- 安装包必须在无 Python、无项目源码、无开发环境变量的干净业务 Mac 上完成真实材料 E2E。
- Worker 必须自包含确定性解析、本机 OCR、模型文件和能力自检。
- 结果 ZIP 必须完整校验、暂存、原子提交和失败回滚；空、部分或过期 metadata 必须失效旧正式证据，且不得覆盖服务端输入文件或业务批准状态。
- Windows、自动安装升级和更广泛分发进入后续独立闸门。

## 迁移顺序

1. P0：架构决策、员工级范围、运行版本、发布边界和 CI 基线。
2. P1：真实身份/owner、Postgres 状态库、私有对象存储直传和 readiness 硬门禁。
3. P2：真实 Golden 全链路、版本化 Profile/适配器和平台内人工复核闭环。
4. P3：自包含 Worker、签名公证、更新、重试恢复和 staging E2E。
5. P4：30 批影子 UAT 后扩大使用范围。

P1 仓库实现完成后仍不是部署完成：真实飞书、Postgres、私有桶、Worker 设备和大文件证据必须按 `docs/labor_p1_integration_runbook.md` 在隔离 UAT 环境验收。历史本地批次因缺少可信 owner 和私有对象证据，不自动导入 P1 权威状态；保留为只读归档，新建 P1 批次用于影子验证。

## 被拒绝方案

- 继续使用 Vercel `run_in_executor` 执行长任务：请求生命周期不可靠。
- 使用 Blob 整份 metadata 作为数据库：缺少跨实例事务和并发控制。
- 真实文件经过 Vercel Function：大文件限制和成本不可控。
- 每来一个供应商继续向公共解析器增加特判：无法形成可回归、可复用的准入机制。
- 首轮依赖外部 AI 提高识别率：隐私边界未批准，且不能替代确定性证据门禁。

## 后果

本决策保留现有 Personal Worker、解析/OCR、安全门禁和报告投资，但要求在扩大供应商前先补齐真实状态、身份、版本和 Golden 闭环。首轮自动化率可能低于继续堆补丁，但错误放行、数据丢失和不可复现发布的风险显著降低。
