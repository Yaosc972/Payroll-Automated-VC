# 海外劳务核对：受控人工复核 UAT 上线闸门

更新时间：2026-07-15
架构依据：`docs/labor_controlled_uat_architecture_adr_v2.md`

## 不可变边界

- 只允许 UAT 核对和人工复核，不允许系统结论直接用于付款。
- 所有正式批次执行员工级核对；总额一致不能跳过员工明细。
- 机器证据通过不等于业务批准，业务批准不等于允许付款。
- 准入单位是“文档家族 + 适配器/Profile 版本”，不是供应商名称；新供应商命中已验证家族时可复用，只有供应商特有差异才新增 Profile。
- 规则、姓名映射、OCR 结果、Profile 和跨仓建议必须先预览、确认、应用，并可回滚。

## 自动硬闸门

当前 P0 readiness 只做开发预检，最多返回 `ready_for_developer_preview`，不能据此开放真实材料。P1–P3 完成后，只有返回 `ready_for_shadow_uat` 且正式上传/任务接口服务端执行同一检查时，才允许管理员影子验证；30 批影子 UAT 退出闸门通过后才能返回 `ready_for_controlled_uat`：

| 要求 | 自动检查 | 人工证据 | 阶段状态 |
| --- | --- | --- | --- |
| 页面/API build 一致，运行源码未变化 | API 契约 v2、源码指纹、runtime gate、客户端契约 | 页面 build 与部署 commit 对照 | P0 已实现并完成开发工作区证据；clean candidate 签署证据待补 |
| 正式批次固定员工级核对 | run metadata、历史批次默认策略 | 抽样报告包含员工级结果 | P0 已实现并完成本轮自动化证据；真实材料抽样纳入 P2 |
| 机器结果与业务复核分层 | 状态字段、结果指纹、服务端复核端点与报告断言 | 业务确认留痕 | P1 代码底座已实现；P2 真实业务复核证据待补 |
| 首轮禁用外部 AI | `SIGMA_LABOR_EXTERNAL_AI_ENABLED=false` | 数据处理边界确认 | P0 已实现 |
| 真实用户、角色和 owner 隔离 | 越权 API 测试 | 企业身份联调记录 | P1 代码底座已实现；真实飞书与 Postgres 联调待环境验收 |
| Postgres 是状态、队列和审计唯一事实来源 | 数据库健康、迁移版本、事务/幂等测试 | 故障恢复演练 | P1 代码底座已实现；真实迁移和恢复演练待环境验收 |
| 经批准的 Private Supabase Storage 直传直下 | 私有桶探针、短期签名上传/下载、大小/哈希校验 | 地域、权限和数据所有者确认 | P1 代码底座已实现；真实桶与大文件 E2E 待环境验收 |
| Worker 用户/设备/短期令牌有效 | 激活、轮换、撤销、过期、版本与 owner 测试 | 设备登记与撤销记录 | P1 身份底座已实现；P3 签名包和干净 Mac 验收待完成 |
| Worker 自包含本机 OCR | 能力自检与干净 Mac E2E | 安装验收记录 | P3 待完成 |
| 签名安装包和更新清单有效 | 签名、SHA-256、最低版本检查 | Developer ID/公证证据 | P3 待完成 |
| 业务批准 Golden 跑完整链路 | release regression job | 业务 reviewer 签字 | P2 待完成 |
| 人工复核且禁止直接付款 | 固定返回值和报告断言 | UAT 培训/操作确认 | 持续要求 |

## 结果级硬闸门

任一条件出现，整批必须阻断机器通过：

- 应付 PDF 没有明确页面角色或权威金额证据。
- 任一文件员工明细缺失、金额未闭合或来源不明。
- 币种冲突、仓库不明、姓名安全门未通过。
- Excel 工作表或字段映射无法确定。
- 抽取质量为 warning 时必须进入 `needs_review`，为 critical 时必须进入 `blocked`；两者都不能 ready。治理候选未确认/未应用/未回滚时同样不得机器通过。
- `batchGuard`、`reconciliationDiagnostics`、`machineCheckStatus` 或机器结论缺失、冲突或未通过。
- 结果状态不是 `已生成差异报告`，或同时标记 `reconciliationScope=total_only_diagnostic` 与 `diagnosticOnly=true` 的显式诊断批次。仅有历史 `total_only_diagnostic` scope 值而没有显式诊断标记时，继续按员工级要求 fail safe。
- PDF/Excel 员工数不是相同正数，`comparisonRows` 未精确覆盖全部员工，或任一行未明确为“通过”。
- 差异报告记录、下载引用、服务端真实文件、`sizeBytes` 或 SHA-256 不一致。
- 结果缺少 `resultInputFingerprint`，或与当前材料、Excel 映射及已生效治理状态不一致。
- 运行版本、适配器/Profile/Worker 版本无法追溯。

reOCR、姓名映射、Profile 和跨仓候选的应用只改变治理状态，不能直接把正式结果改写为通过；上传材料、Excel 映射或已生效治理状态变化后，旧结果必须立即失效并整批重新核对。任务发布必须同时校验 `taskGenerationId` 与输入快照；旧任务的进度、失败、结果和 reservation release 不得修改新任务。

Worker 结果 ZIP 必须先完整校验和暂存，再原子提交并支持失败回滚。空、部分或过期 metadata 不能与旧通过证据拼接；正式报告的 `sizeBytes`、SHA-256 必须与暂存文件一致，且只有同一 `taskGenerationId` 的完整结果写入 accepted marker 后 job 才能完成为成功。Worker 无权覆盖服务端输入文件记录、业务批准、付款或免人工复核状态，服务端必须将业务复核重置为待确认。

不得以整批 90% 覆盖率抵消单个关键文件失败。

## P0 发布基线

- 模块版本：`0.5-uat`
- API 契约版本：`2`
- 正式核对范围：`employee_detail_required`
- 页面和公共 access 必须展示/返回版本、API 契约、build 与运行状态；source ref、进程启动时间和完整源码指纹仅允许鉴权后的 readiness 返回。
- 服务启动后源码变化时，页面锁定正式操作；API 返回 `LABOR_SERVICE_RESTART_REQUIRED`。
- 正式浏览器写接口无条件校验页面/API/build 契约，部署环境不能关闭该检查。
- 跨批次复用的 Supplier Profile 只允许从发布包内 `data/supplier_profiles/` 加载；外部或不存在的全局路径使运行 build 变为 `unverified`。经完整审批的 run-local active Profile 只在当前批次内生效并绑定输入指纹，不能作为跨批次发布配置；跨批次推广进入 P2 Golden 晋级流程。
- 工作台首页、海外劳务用户页、运维页和 Worker renderer 不得加载任何外部 HTTP(S) runtime；共享样式、关键资产和 Worker 直接打包依赖必须纳入 build 指纹、必需文件哨兵与 CI 范围。
- Personal Worker 任务必须携带最低 Worker 版本。
- 低版本或非法版本 Worker 必须收到明确升级状态，不能伪装为“暂无任务”。
- Worker 在 claim、result 和 complete 阶段均重新校验当前最低版本；已领取的旧租约不能跨版本升级提交。
- 公共 access 不暴露 source ref、完整源码指纹或进程启动时间；这些信息仅在鉴权运维接口中可见。
- `.gitignore`/`.vercelignore` 必须排除 Worker 依赖、构建物、安装包和本地真实材料渲染产物。
- 海外劳务 PR CI 必须运行 Python 劳务测试、Worker JS 测试、越界路径检查和原始/未知二进制材料阻断；不提供 `workflow_dispatch` 旁路，最终 gate 必须要求 scope/Python/Worker 全部成功。
- 任何 Vercel runtime，以及 `SIGMA_WORKBENCH_HOME=/tmp/...` 且 `SIGMA_LABOR_STORAGE_BACKEND=blob` 的明确请求作用域组合，无 Personal Worker 就必须拒绝整批长任务；`uat_full` 等旧 access 标记不得成为旁路。
- 同一请求作用域判定下，本地材料扫描、replay plan、dry-run 和 material-run 创建接口必须返回 `LABOR_LOCAL_MATERIAL_TOOL_DISABLED`。
- 仓库中的图像回归 fixture 只能使用合成标识和聚合金额，不得保存真实员工姓名或 OCR 证据原文。
- P0 本地 metadata/Worker/删除操作使用同批次进程内锁；同批次任务单活并使用 reservation token、`taskGenerationId` 和输入快照 CAS。它不替代 P1 的 Postgres 多实例事务与持久化状态机。

## 发布证据包

每个 UAT 候选至少保留：

1. 部署 commit/build ID 和 source ref。
2. `production-readiness` 脱敏输出。
3. Python/Worker/静态页面 CI 结果。
4. 业务批准 Golden 全链路摘要。
5. 大文件、断网、Worker 崩溃、租约恢复、重复提交和越权测试结果。
6. DMG 签名、哈希、版本和干净业务 Mac 验收结果。
7. 回滚目标和数据保留/删除验证记录。

P1 权威状态迁移定义见 `docs/sql/labor_p1_state.sql`，配置和验证顺序见 `docs/labor_p1_integration_runbook.md`。readiness 只有在迁移版本标记、真实身份、Postgres 状态/队列、私有签名存储和数据库 Worker 身份全部通过时才放行正式写接口。仓库中的完成状态仅代表代码底座和自动化证据，不代表真实 UAT 环境已经验收；真实数据库、身份、对象存储、密钥和部署仍由 UAT 环境负责人配置，仓库不保存生产凭据。
