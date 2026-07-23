# 海外劳务 P1 影子 UAT 接入手册

更新时间：2026-07-16
适用范围：1–2 名管理员的隔离影子 UAT；不允许直接付款。

## 本阶段结论

仓库已具备 P1 代码底座：复用首页飞书会话，服务端确定用户/角色/owner；Postgres 保存批次、文件、映射、复核、任务、设备和审计；Private Supabase Storage 提供短期签名输入上传与报告下载；本人 Worker 使用可轮换、可撤销、会过期的设备令牌。正式写接口以及 Worker 领取、读入、心跳、回传、完成和失败协议执行同一 P1 readiness。

这不等于环境已经上线。没有完成下方真实联调时，`SIGMA_LABOR_P1_REQUIRED` 不得在面向业务的环境开启。

## 1. 变更前检查

1. 新建隔离 UAT Postgres 和 private Supabase bucket，确认地域、数据所有者、管理员和保留策略。
2. 备份现有 Postgres；检查旧 P0 `labor_jobs` 是否存在无 owner 或无对应批次的历史记录：

```sql
select count(*) from public.labor_jobs
where coalesce(metadata_snapshot ->> 'ownerUserId', '') = '';
```

3. 历史本地批次不自动导入。它们缺少可信登录 owner 或私有对象证据，继续只读归档；影子 UAT 从新批次开始。
4. 如果旧 `labor_jobs` 有需保留的记录，先按审批结果补齐 `labor_runs` 和 owner，再执行迁移。不要为通过迁移直接删除历史记录。

## 2. 数据库迁移

使用应用私有数据库角色在一个事务中执行：

```text
docs/sql/labor_p1_state.sql
```

脚本会升级旧 P0 队列表、校验 owner/任务类型/run 外键，并在全部成功后写入 `labor_schema_versions(component='labor_p1', version=1)`。任一旧记录不满足约束时整个事务回滚，readiness 继续阻断。

迁移后只做只读确认：

```sql
select component, version, applied_at
from public.labor_schema_versions
where component = 'labor_p1';

select conname, convalidated
from pg_constraint
where conrelid = 'public.labor_jobs'::regclass
  and conname in ('labor_jobs_run_fk', 'labor_jobs_type_check', 'labor_jobs_owner_not_blank');
```

预期：版本为 `1`，三个约束均为 `convalidated=true`。

## 3. 环境配置

按 `.env.example` 的 P1 段配置真实环境变量，关键原则：

- `ADMIN_DATABASE_URL` 继续服务现有首页登录、用户和角色；`SIGMA_LABOR_DATABASE_URL` 服务劳务权威状态，可指向同一受控 Postgres。
- Vercel 函数使用适合无服务器短连接的 Postgres transaction-pooler 地址；不要把数据库直连地址作为函数实例的默认连接串。上线前由数据库管理员核对 SSL、连接上限和池化模式。
- 队列默认复用 `SIGMA_LABOR_DATABASE_URL`；没有评审理由不要单独设置 `SIGMA_LABOR_JOB_DATABASE_URL`。
- P1 存储固定 `SIGMA_LABOR_STORAGE_BACKEND=supabase`，bucket 必须是 private。
- P1 会在服务端拒绝旧 multipart 上传和本地报告回退；Postgres 本地缓存不再整批同步到旧的无 owner 对象路径。
- `SUPABASE_SERVICE_ROLE_KEY`、数据库 URL、飞书 Secret 和运维 Token 只存在服务端环境，不进入浏览器、Worker、仓库或报告。
- 不配置 `SIGMA_LABOR_WORKER_TOKENS`；它只用于 P1 关闭时的本地兼容测试。
- `SIGMA_ENABLE_MOCK_LOGIN=false`、`SESSION_COOKIE_SECURE=true`、`SIGMA_LABOR_EXTERNAL_AI_ENABLED=false`。
- P1 环境变量通过 Vercel Project Settings 按 Preview/UAT 范围管理，不在 `vercel.json` 写死存储后端或真实值；环境变量变更后必须创建新部署才会生效。

先设置 `SIGMA_OVERSEAS_LABOR_ACCESS=disabled`，再开启 `SIGMA_LABOR_P1_REQUIRED=true` 运行完整 readiness 探针；确认通过后才恢复隔离 UAT 的模块访问。

### 3.1 只读环境预检

先对隔离 Preview 地址执行不带 Token 的部署契约检查：

```bash
python3 tools/labor_p1_preflight.py https://<preview-host>
```

它只读取飞书配置状态和劳务访问契约，不创建批次、不上传文件，也不输出 Secret。若返回 `deployment_contract_stale`，说明该地址仍是旧版本；若返回 `p1_mode_not_enabled`，说明 P1 环境尚未完整启用。

需要检查服务端权威 readiness 时，只通过当前 shell 的环境变量传入 UAT 运维 Token：

```bash
export SIGMA_LABOR_OPERATIONS_TOKEN='<仅保存在当前安全终端>'
python3 tools/labor_p1_preflight.py https://<preview-host>
unset SIGMA_LABOR_OPERATIONS_TOKEN
```

不要把 Token 写进命令参数、仓库、报告或 CI 日志。工具退出码 `0` 表示全部通过，`2` 表示仍有阻断；以输出中的 blocker code 为准，不凭页面是否能打开判断环境可用。

## 4. 开启前验收

自动合同回归先执行：

```bash
python3 -m pytest -q \
  tests/test_labor_p1_identity.py \
  tests/test_labor_p1_upload_api.py \
  tests/test_labor_p1_worker_identity.py \
  tests/test_labor_worker_jobs.py \
  tests/test_labor_worker_jobs_postgres.py \
  tests/test_labor_worker_api.py
```

这些测试证明 owner 绑定、跨用户文件路由阻断、签名上传协议、设备令牌、队列领取和私有报告下载的代码合同；不能替代下面的真实 UAT。真实证据应记录 Preview URL、`buildId`、执行时间、两名测试用户、状态码和脱敏对象计数，不记录 Cookie、Token、数据库 URL、对象 key 或员工材料内容。

1. 使用现有首页飞书登录，以管理员和无权限账号分别验证页面准入。
2. 带运维 Token 调用 `/api/labor/production-readiness`；预期 `status=ready_for_p1_integration`、`p1.ready=true`，且仍为 `manualReviewRequired=true`、`directPaymentAllowed=false`。
3. 在海外劳务页面激活本人核对助手，确认页面先显示“待连接”，Worker 首次版本检查后显示真实版本和在线时间。
4. 撤销设备后确认旧令牌立即收到 401；令牌过期后 Worker 明确提示从页面重新激活，不能显示成普通断网。
5. 用两个用户分别新建批次，交叉读取、下载、映射、复核、任务和 Worker 领取都必须失败。
6. 上传至少一组接近文件上限的 PDF/Excel：浏览器直传 private bucket，Worker 下载后重新校验大小和 SHA-256；篡改文件必须阻断正式结果。
7. 断开 Worker、让租约过期、重复提交旧结果，再恢复；新代次状态不得被旧任务覆盖。
8. 生成报告并确认下载是短期签名跳转；对象 key、服务角色密钥和原始错误不得出现在页面或 readiness。
9. 删除测试批次后，确认旧兼容前缀和该 owner/run 的 P1 输入、输出对象均被删除，其他 owner 或其他批次对象不受影响。

## 5. 回滚

- 先设置 `SIGMA_LABOR_P1_REQUIRED=false`，阻止继续创建 P1 正式写入；不要删除数据库或对象。
- 保留 Postgres 和 private bucket 作为审计证据，撤销已签发 Worker 设备令牌。
- 回滚应用版本后复核首页登录与其他模块；本轮不修改它们的业务逻辑。
- 数据删除只按批准的保留策略执行，不以回滚为由清理真实材料。

## 6. 仍不属于 P1 完成范围

- 业务批准 Golden 全链路和新文档家族晋级（P2）。
- Worker DMG 签名、公证、干净 Mac 安装、大结果包直传优化和自动更新（P3）。
- 30 批真实影子 UAT 退出闸门及扩大用户范围（P4）。
