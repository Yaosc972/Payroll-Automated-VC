# 海外劳务 P1 隔离 UAT 验收记录（2026-07-16，更新于 2026-07-20）

状态：**基础设施、飞书配置、Private Storage、本人 Worker 与统一 readiness 已取得基础闭环证据；当前 Worker `0.3.3` 在线，当前 Preview 已用合成材料完成创建、私有直传、字段映射、完整核对、冷启动恢复和 Excel 报告下载。2026-07-20 已进一步完成接近单文件上限的 PDF/Excel 在线直传、Worker 预检与完整 reconcile：整批 PDF/Excel 均为 `USD 120.00`，差额 `0`，2 人全部一致，0 项待确认。P1 仍缺同尺寸篡改输入的线上拒绝、租约恢复、隔离删除/保留和第二真实用户隔离证据；业务 HTML 报告的签名下载参数已修复并发布，但受当前自动化浏览器跨域策略限制，仍需补一次普通浏览器实下载证据。Goal 保持 paused，暂不可判定完成。**

本记录只保留资源名称、状态码、数量和脱敏结论，不记录 Cookie、Token、数据库 URL、对象 key、员工资料或任何 Secret。

## 1. 隔离边界

- Supabase 项目：`sigma-overseas-labor-uat-20260716`，区域 `us-east-1`。
- Private Storage bucket：`sigma-labor-runs-uat`，`public=false`，单文件上限 50 MB。
- Vercel 项目：`sigma-workbench-uat`。
- 稳定 Preview：<https://sigma-workbench-uat-yaosc972-yaosc-s-project.vercel.app>。
- 当前部署：`dpl_Az5mmzcjhU3wWU1hJkLQuZV26yQx`，`target=preview`，`status=Ready`，构建 `buildId=local-0c5a4dccff`。
- 2026-07-20 已将稳定 UAT 别名切换到上述 Worker `0.3.3` / P1 下载修复候选部署；隔离 Supabase 项目状态为 `ACTIVE_HEALTHY`，没有发现环境漂移。
- 2026-07-20 只读检查 Vercel 环境范围：全部 P1、飞书、Postgres、Supabase 和 Worker 变量仅绑定 `Preview`；该 UAT 项目的 `Production` 范围只有一个此前已存在且与本次无关的 `BLOB_READ_WRITE_TOKEN`。P1 已固定 `SIGMA_LABOR_STORAGE_BACKEND=supabase`，本次不删除或修改该无关变量，也没有创建 Production 部署。
- 本次没有 Production 部署，没有修改生产项目环境变量、数据库或对象存储。

## 2. 已取得的权威证据

### Postgres

- `labor_schema_versions(component='labor_p1')`：版本 `1`。
- P1 表：`9/9` 存在。
- P1 表 RLS：`9/9` 已启用。
- `labor_jobs` 关键约束：`3/3` 已验证。
- 复核索引：`4/4` 存在。
- 运行角色使用 transaction pooler，可完成只读和事务内写入/回滚探针；无 schema `CREATE` 权限。

### Private Supabase Storage

- bucket 私有性检查通过。
- 服务端写入、读取、删除探针通过。
- 浏览器短期签名直传与短期签名下载能力检查通过。
- 删除结果以 Storage 对象列表为权威依据，避免 CDN 缓存导致误报。

### Vercel Preview 与统一 readiness

- `/api/labor/access`：版本 `0.5-uat`，`p1.required=true`，上传模式为 `signed_private_direct`。
- 运行构建：`buildId=local-0c5a4dccff`、`status=current`、`runtimeSourceCurrent=true`。
- Vercel Python bundle 会省略桌面 Worker 子目录的 `package-lock.json`；服务端运行哨兵已与 Worker CI 完整性检查分层。Worker CI 仍使用该 lockfile 执行 `npm ci`。
- UAT Preview 运维令牌已在单个进程内安全轮换；候选部署与稳定 UAT 地址的一键预检均返回 `ready=true`、`status=ready_for_p1_integration`、`p1.ready=true`、`blockers=[]`。令牌未回显、未落盘，命令结束后已从本机进程环境清除。
- 当前保持 `manualReviewRequired=true`、`directPaymentAllowed=false`。
- Worker `0.3.3` / P1 下载修复候选切换到稳定 UAT 后，公开页面再次确认 `version=0.5-uat`、`p1.required=true`、`uploadMode=signed_private_direct`、`runtimeSourceCurrent=true`。因 Vercel Sensitive 运维令牌不可回读，本次未携令牌复跑服务端 readiness；没有轮换或回显任何 Secret。
- 当前部署上的正式 reconcile、Worker claim/input/result/complete 均通过 P1 统一 readiness 门禁并返回成功；该门禁只在 Postgres 状态/队列、Private Storage 探针、真实登录和短期 Worker 身份全部 ready 时放行。
- 审计发现并修复了 `httpx/httpcore` INFO 请求日志会记录完整短期签名 URL 的问题。新部署的 Worker 与下载请求运行日志 `internalLogCount=0`、`containsSignedQuery=false`；业务报告下载为 `307` 短期签名跳转。

### 本人 Worker

- 2026-07-19 基础闭环时页面显示核对助手在线；本地 Worker 版本 `0.3.1`，进程存活。该描述是历史验收证据，不代表 2026-07-20 的当前运行状态。
- 2026-07-20 发现旧桌面助手将设备令牌作为 `--token` 命令行参数传给 Worker，且服务端把同一长期令牌写入 `sigma-workbench://` 激活 URL。该描述是事故发现时状态；两个暴露源已修复，后续 `0.3.3` 已重新激活并上线验收。
- 两个暴露源均已在源头修复：Electron 只向 Worker 传入 `--token-stdin` 标志，通过一次性标准输入管道交付令牌；Worker CLI 的明文 `--token` 入口已移除。页面激活 URL 现在只携带有效期 5 分钟的 `sigma_labor_a1_` 一次性码，桌面助手通过 HTTPS、`no-store` 端点原子交换得到真正的 `sigma_labor_w1_` 设备令牌；激活码交换后立即失效。激活码和设备令牌均只以 SHA-256 保存，复用现有 `labor_worker_tokens` 表，没有新增 schema 或平行状态层。
- 一次性激活码与标准输入交付链路在 `0.3.2` 完成修复；当前安装并运行的是后续 `0.3.3` Worker，服务端门禁也已要求 `0.3.3`。桌面 Node 测试 `10 passed`、语法检查通过；P1/Worker/Postgres/Private Storage/上传/租约/归档/交接/构建合同宽回归 `213 passed`，其中 Worker 身份与激活专项 `14 passed`。
- 修复后的 PyInstaller Worker、macOS App 和 DMG 均已成功构建；当前 `/Applications/Σ海外报账核对助手.app` 内置 Worker `0.3.3` 已重新激活并在线。安全状态文件只读取 allowlist 字段；本轮近上限工作表预检和正式 reconcile 均由该 Worker 领取并完成。
- 配套 API 已从干净临时制品发布为 Preview `dpl_Az5mmzcjhU3wWU1hJkLQuZV26yQx`，稳定 UAT 别名已切换，生产未部署。设备撤销与令牌过期的线上验收仍需单独完成，不能用本地停进程代替服务端证据。
- 当前 Preview 合成批次的工作表预检与完整 reconcile 均已被本人 Worker 领取并完成；页面显示工作表 `Bill`、两行员工样例及 `Name / Hours / Amount / Employee ID / Currency` 自动映射，随后产出并持久化完整报告。强制刷新后结果仍保持完成态，没有再被 Vercel 冷启动恢复逻辑覆盖为任务中断。

### 未登录线上安全边界

| 检查 | 实际结果 |
| --- | --- |
| 批次列表 | `401 LABOR_AUTH_REQUIRED` |
| 创建批次 | `401 LABOR_AUTH_REQUIRED` |
| 读取任意批次 | `401 LABOR_AUTH_REQUIRED` |
| 创建上传意图 | `401 LABOR_AUTH_REQUIRED` |
| 下载任意批次报告 | `401 LABOR_AUTH_REQUIRED` |
| Worker 无令牌领取任务 | `401` |
| 无运维令牌读取 readiness | `401` |

### 自动合同回归

按运行手册列出的当前代码针对性回归合计 `93 passed`（2026-07-19 复跑）：

- P1 会话 owner 与跨用户隐藏；
- 签名上传、清单固化、签名下载；
- Worker 设备令牌签发、轮换、撤销和过期；
- Postgres 队列独占领取、租约和代次；
- Worker 输入、结果验收、篡改阻断和私有报告发布。

本次补齐了 5 个此前缺少的明确回归：令牌记录已撤销或过期时不得更新设备在线时间、撤销设备同时撤销其全部活动令牌、浏览器撤销设备后旧 Worker Bearer 立即返回 `401`、过期租约被新设备接管后旧设备不能完成任务，以及上传意图接受当前近上限 PDF/Excel 规格而在超过应用边界 1 byte 时分别返回 `413`。其中撤销/租约聚焦回归 `4 passed`，存储与上传边界套件 `21 passed`，随后运行手册完整合同套件 `93 passed`。

这些回归只证明代码合同，不能替代真实飞书账号、真实浏览器和真实 Worker 验收。

另行在当前最终代码复跑 P1 迁移、Private Storage、公开预检、readiness、身份、签名上传和任务交接补充套件，结果为 `63 passed`（2026-07-19）。日志脱敏与 Worker 冷启动恢复的聚焦回归为 `4 passed`。

此外，此前同一干净 Preview 构建物通过 Python 海外劳务完整回归 `922 passed`，独立 Worker 包通过 `9/9` 检查；这两项是历史构建证据，本次更新没有把它们冒充为重新执行结果。`0.3.2` 本次实际重新执行的证据为桌面 `10 passed`、Worker 身份专项 `14 passed` 和相关宽回归 `213 passed`。

## 3. 飞书配置接通证据

UAT 已复用首页现有飞书应用，没有新增身份系统：

- `FEISHU_APP_SECRET` 已配置为 `sigma-workbench-uat` 的项目级 Sensitive 变量；
- 环境范围只有 `Preview`，没有绑定 Production；
- `/api/auth/feishu/config` 返回 `configured=true`；
- UAT 运维令牌已作为 Preview-only Vercel Sensitive 变量存在；此前通过单进程内存轮换完成服务端一键预检，明文未回显、未落盘、未写入仓库或验收记录；
- 当前已有一名真实飞书用户完成 OAuth 登录并取得单用户运行证据；当前验收人没有第二个飞书账号，双用户验收必须在上线前临时邀请一名同事使用其现有账号完成，不能用同一账号重复登录或客户端模拟身份替代。

UAT 回调地址为：
`https://sigma-workbench-uat-yaosc972-yaosc-s-project.vercel.app/api/auth/feishu/callback`

## 4. 真实验收证据与剩余项

### 2026-07-19 当前 Preview 单用户实测

- 使用现有飞书登录用户创建合成批次 `labor_20260719_102248_307892_8a019cda`，没有新建平行身份或测试会话。
- 通过页面将 1 个合成 PDF（2,514 bytes）和 1 个合成 Excel（5,022 bytes）按签名地址直传 Private Storage；本地 Worker 下载副本的 SHA-256 字段均存在。
- Worker 已领取并完成该批次的工作表预检任务；页面读取到 `Bill` 工作表并显示两名合成员工及自动字段映射。
- Worker 在当前部署重新完成完整 reconcile：PDF 总额 `$120.00`、Excel 总额 `$120.00`、总差额 `$0.00`，两名员工金额与 `12` 小时工时均一致。
- 生成报告 `20260719_222641_350175.xlsx`，大小 `19,050` bytes，SHA-256 为 `acb515f1236955b88ae8fa8bade1a8aaf2e91e8d690fc3c5052b1043717e703c`。工作簿含 `15` 个工作表，关键汇总与明细值一致，公式错误扫描为 `0`。
- 浏览器下载请求在当前 Preview 返回 `307`，下载后文件可读取；新部署运行日志未再记录签名参数。
- 任务完成后执行强制刷新，页面仍恢复同一份 `$120.00 / $120.00 / $0.00` 结果，证明 Worker 完成结果未被启动恢复覆盖。
- 合成材料不含真实员工资料；本次没有 Production 部署、数据库迁移或环境变量修改。
- 当前单用户“创建/上传/映射/任务/持久化/下载”闭环已通过；仓库字段和金额口径仍按产品门禁保持待人工确认，不冒充业务放行。

### 近上限 good 路径在线通过；篡改阻断待验收

- 最终合成 PDF：`49,285,028` bytes（同时低于 Storage 的 `50,000,000` bytes 边界与应用的 50 MiB 单文件门禁），1 页，权威发票总额 `USD 120.00`，仓库 `25`，两名合成员工明细可确定性解析。SHA-256：`68bb9d4f08ae009d478218c35a7899d02f5de50f7de35225c51a611c34820412`。
- 最终合成 Excel：`19,512,933` bytes（低于 20 MiB 工作簿门禁），`Bill` 工作表含两名合成员工、`12` 小时、`USD 120.00` 和仓库 `25`；`artifact-tool` 重新导入、关键区域检查和渲染均通过。SHA-256：`45c9e5ae3ef55fabef7d2f659b981d69ab5bfcba4dfd4b335e1ef26738ba0649`。
- 稳定 UAT 批次 `labor_20260720_015037_839596_a5e62bc5` 完成两文件浏览器签名直传、Worker `0.3.3` 工作表预检和正式 reconcile。页面结论：PDF `$120.00`、Excel `$120.00`、差额 `+$0.00`、0 项待确认、2 人全部一致，可进入业务确认。
- 下载 Excel 明细 `20260720_095549_312259.xlsx`，大小 `18,612` bytes，SHA-256：`dc5fec255450df792f714348ce71d6439d79e04ed4ca822deb15cab38ba91308`。重新导入确认 15 个工作表完整；`核对结论=通过`、仓库 `25` 证据状态 `authoritative`、信号诊断 `ok`、异常数 `0`。
- 业务 HTML 报告在线点击暴露出 Supabase 签名 URL 未带下载查询参数的问题。根因回归先失败后通过，修复将 `download=<filename>` 追加到短期签名 URL，相关存储/路由测试 `10 passed`，并发布到当前 Preview。自动化浏览器随后因跨域策略返回 `ERR_BLOCKED_BY_CLIENT`，没有取得普通浏览器下载事件，因此该项仍保留一次实下载复验。
- 两个文件均另有同尺寸、单字节变化的篡改副本，SHA-256 分别为 `53ece025f73ca87486271f3c583a2be183537308f979943912134a0873271cca` 和 `e21b274a7a29f9bba3e3b1aae7338644bdd80e9b80e7ff96027eabcd4521aa91`。
- Worker 新增同尺寸、单字节篡改输入回归：私有签名下载后的流式 SHA-256 不一致会删除本地暂存文件、阻止核对引擎启动并向队列报告失败；个人 Worker 与包边界套件 `20 passed`。
- good 文件近上限在线路径已经通过；同尺寸篡改对象的线上注入与正式结果阻断仍未执行，不能用本次 good 结果或代码回归替代。

### 仍缺的验收项

- 需验证用户 B 无海外劳务权限时，页面和 API 均返回 `403 LABOR_MODULE_FORBIDDEN`。
- 需验证第二名有权限用户无法读取、修改、下载或让 Worker 领取用户 A 的批次，返回统一 `404 LABOR_RUN_NOT_FOUND`。
- 第二个真实账号参与前，无法把代码合同测试冒充双用户线上隔离证据。
- 新飞书用户默认保持待授权；真实验收要先以非海外劳务角色取得 `403`，再经 UAT 权限审计明确授予 `overseasAdmin` 后取得跨 owner `404`。不能用客户端模拟角色或本地存储冒充服务端授权。
- 接近单文件上限的 PDF/Excel 私有直传、Worker 下载复核与完整结果已取得线上证据；仍需完成同尺寸篡改对象的线上拒绝，且业务 HTML 报告需补一次普通浏览器实下载。
- 撤销设备后旧令牌立即失效；租约过期可恢复，旧代次结果不能覆盖新代次。
- 删除测试批次只删除该 owner/run 对象，不影响其他用户或批次。

当前部署已有专用近上限合成 UAT 批次，不再依赖旧失败任务作为验收依据；该批次已证明单用户近上限 good 路径、完整核对和 Excel 下载闭环，但不能冒充双用户隔离、线上篡改阻断、设备撤销、租约恢复或跨 owner 删除证据。

上述项目全部取得当前 Preview 的真实证据后，才可把 Step 1 标记为完成。

## 5. 2026-07-20 逐项完成审计

| 目标要求 | 当前判定 | 权威证据或缺口 |
| --- | --- | --- |
| 复用首页飞书登录，不新建平行身份 | 已证明 | 当前 Preview 真实飞书用户单用户闭环；服务端会话 owner 合同回归通过 |
| Postgres 迁移与版本检查 | 已证明 | `labor_p1=1`、P1 表 `9/9`、RLS `9/9`、关键约束 `3/3`、复核索引 `4/4` |
| Private Supabase Storage | 已证明 | bucket 私有，写/读/删、签名直传/下载和列表权威删除探针通过 |
| 用户设备 Worker 激活 | 已证明当前在线闭环 | Worker `0.3.3` 已重新激活并完成近上限工作表预检、正式 reconcile 和报告持久化；设备撤销与令牌过期仍作为独立安全场景待验收 |
| 统一 readiness 强制门禁 | 已证明 | 同一部署曾携 UAT 运维令牌返回 `ready_for_p1_integration`；正式上传和 Worker 协议已在该部署通过门禁。2026-07-20 公开预检再次通过飞书与 P1 部署合同，因 Sensitive Token 不可回读而按设计跳过服务端 readiness，不轮换 Secret |
| 一键预检与明确 blocker | 已证明 | `tools/labor_p1_preflight.py` 输出结构化检查、blocker code 和退出码；不回显 Token |
| 单用户上传/任务/下载证据 | 已证明 | 合成小文件完成私有直传、字段映射、Worker 任务、刷新恢复和可读报告下载 |
| 接近文件上限的真实直传与 Worker 哈希复核 | good 路径已证明；篡改拒绝未证明 | `labor_20260720_015037_839596_a5e62bc5` 完成近上限签名直传、Worker `0.3.3` 预检和 reconcile；PDF/Excel 均为 `$120.00`，Excel 报告 15 个工作表可读。仍缺同尺寸篡改对象线上拒绝 |
| 设备撤销、令牌过期和租约恢复 | 未证明 | 代码合同回归通过，Worker `0.3.3` 当前在线；仍需在受控窗口撤销设备并取得旧令牌 `401`，重新激活后完成租约过期接管和旧结果阻断演练 |
| 双用户 `403` 与跨 owner `404` | 未证明 | 当前验收人没有第二个飞书账号，需要上线前由一名同事使用现有企业账号补测 |
| owner/run 隔离删除 | 未证明线上证据 | 本地 Supabase 生命周期回归已证明只删除目标 owner/run；当前 Preview 尚未执行并核对脱敏对象计数 |
| 不部署生产、不泄露 Secret、不碰无关改动 | 当前持续满足 | Worker `0.3.3` 与本轮下载修复均从目标干净临时制品发布为 Preview；验收记录不含 Cookie、Token、数据库 URL 或对象 key，未执行 Production 部署，也未修改无关模块 |

结论：代码底座、隔离基础设施、单用户闭环和近上限 good 路径已达到 P1 验收前提；同尺寸篡改拒绝、设备/租约恢复、owner/run 隔离删除、第二真实用户隔离及业务 HTML 普通浏览器实下载仍缺权威证据。Goal 保持 paused，不能因本轮 good 路径通过而提前关闭。
