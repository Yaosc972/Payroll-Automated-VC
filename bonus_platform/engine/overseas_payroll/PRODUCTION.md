# 海外薪资生产接入说明

## 已采用的链路

浏览器先向 Sigma 创建任务，再使用短期签名 URL 将文件直接上传到 Supabase 私有桶。Vercel 只处理任务元数据，不接收工资文件正文。Postgres `labor_jobs` 队列把 `overseas_payroll` 任务交给本人核对助手；Worker 下载输入、校验大小和 SHA-256、执行原解析器、直传结果，浏览器轮询任务后通过短期签名 URL 下载。

本地开发没有 Supabase 时仍走相同任务 API，但文件落在本地输出目录，并由一个进程内线程处理。该回退只用于本地验证，不能作为 Vercel 生产长任务方案。

## 生产环境必须配置

- `SIGMA_LABOR_STORAGE_BACKEND=supabase`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`（仅服务端，禁止进入浏览器或 Worker）
- `SIGMA_LABOR_SUPABASE_BUCKET`（必须是私有桶）
- `SIGMA_LABOR_JOB_BACKEND=postgres`
- 项目现有 Postgres 数据库连接配置，并应用现有 `docs/sql/labor_jobs.sql`
- 可用的本人核对助手，版本至少 `0.3.16`
- 平台现有可信登录、飞书 OAuth 回调和 `overseas` 模块权限配置

不需要为海外薪资新增数据库表；任务队列复用 `labor_jobs`，任务清单和文件放在私有对象存储。

## 上传性能与容量边界

- 单文件上限 40 MB，单任务合计上限 80 MB，最多 12 个文件。
- 浏览器最多并发上传 3 个文件，并对网络失败自动重试 3 次。
- 文件不再经过 Base64，避免约三分之一的体积膨胀，也不再占用 Vercel 函数的请求体和响应体带宽。
- 当前实现使用标准签名 PUT。若生产中经常出现大于 6 MB 的文件或弱网断线，下一步应接入 Supabase TUS 可续传上传；这不需要改页面视觉，但需要增加客户端上传协议实现。

## 安全与运维要求

- Supabase 桶保持私有；上传和下载只发短期签名 URL。
- 配置对象存储生命周期规则，自动删除 `payroll-inputs`、`payroll-outputs` 和 `payroll-task` 前缀下超过 14 天的数据。代码中的 `expiresAt` 是任务过期标记，不会代替存储侧真实删除。
- 限制服务角色密钥只在 Vercel 服务端存在；Worker 仅持有现有设备令牌。
- 生产发布前验证 Worker 包包含 `bonus_platform.engine.overseas_payroll` 的 Python 模块和 YAML 资源。
- 监控队列等待时间、失败率、上传耗时、对象存储错误和 Worker 心跳。解析结果仍需按现有业务流程人工复核。

## 上线验收

1. 使用飞书企业账号登录，确认无 `overseas` 权限的用户收到 403，有权限用户可以进入页面。
2. 分别上传 1 MB、10 MB、接近 40 MB 的样本，确认浏览器请求中没有文件正文经过 Vercel API。
3. 停止 Worker 后创建任务，确认任务保持排队；恢复 Worker 后任务继续完成。
4. 中断一次上传，确认自动重试；弱网大文件场景若仍不可接受，再启用 TUS 可续传。
5. 确认下载 URL 过期后失效，并验证 14 天生命周期规则实际删除对象。
