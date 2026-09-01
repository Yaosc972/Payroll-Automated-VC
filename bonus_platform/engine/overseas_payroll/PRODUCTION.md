# 海外薪资生产接入说明

## 已采用的链路

浏览器先向 Sigma 创建任务，再使用短期签名 URL 将文件直接上传到 Supabase 私有桶。工资文件正文不经过浏览器到 Vercel API 的上传请求，因此不会受到 Function 请求体大小限制，也不会产生 Base64 膨胀。

文件确认完成后，`POST /api/overseas-payroll/tasks/{task_id}/enqueue` 在 Vercel Python Function 内执行原解析器：服务端从私有桶下载输入、校验大小和 SHA-256、生成结果并直接写回私有桶。浏览器继续使用现有任务状态与短期签名 URL 下载结果。海外薪资不再依赖个人电脑 Worker，也不要求 `labor_jobs` Postgres 队列。

本地开发没有 Supabase 时仍走相同任务 API，文件落在本地输出目录，并由一个进程内线程处理。这个回退只用于本地验证。

## Vercel 套餐与执行边界

- `vercel.json` 已开启 Fluid Compute，并把 `api/index.py` 的 `maxDuration` 设为 300 秒，便于用脱敏/合成材料做技术验证。
- Vercel Hobby 仅允许个人、非商业用途，不能承载公司的生产薪资系统。生产必须使用公司名下的 Pro/Enterprise 项目，并完成数据所有者、法务与安全审批。
- 不得把真实员工工资文件上传到个人 Hobby 或试用项目。除商业使用限制外，Vercel 当前服务条款对 Hobby/试用账号内容另有模型训练约定；生产账号需按公司数据政策核对并关闭不适用的数据使用选项。
- Function 在处理期间会保持 enqueue 请求打开；任务状态和结果写入 Supabase，不依赖 Vercel 临时目录。
- 当前方案没有耐久队列自动重试。函数超时、实例中断或超过免费额度时，本次任务可能停留在处理中，用户需重新提交。
- 上线前必须在获批的隔离 UAT 中用代表性最大样本测量 P95 耗时。任何工具接近 240 秒就应升级为 Vercel Queues + Python Celery、Pro 长函数，或独立容器 Worker。

## 生产环境必须配置

- `SIGMA_LABOR_STORAGE_BACKEND=supabase`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`（仅 Vercel 服务端，禁止进入浏览器）
- `SIGMA_LABOR_SUPABASE_BUCKET`（必须是私有桶）
- 平台现有可信登录、飞书 OAuth 回调和 `overseas` 模块权限配置

海外薪资本身不再要求 `SIGMA_LABOR_JOB_BACKEND=postgres`、`labor_jobs` 表或个人核对助手；如果平台的海外劳务等其他模块仍使用这些能力，应保留其现有配置。

## 上传性能与容量边界

- 单文件上限 40 MB，单任务合计上限 80 MB，最多 12 个文件。
- 浏览器最多并发上传 3 个文件，并对网络失败自动重试 3 次。
- 文件不经过 Vercel 上传代理和 Base64，上传速度主要由用户到 Supabase 所在地域的网络决定。
- Vercel Function 会从 Supabase 下载输入并在内存中解析；应把 Vercel Function 与 Supabase 放在相近地域，减少下载延迟和跨区流量。
- 当前使用标准签名 PUT。若生产中经常出现大于 6 MB 的文件或弱网断线，下一步接入 Supabase TUS 可续传上传；无需改变页面视觉，但需替换上传协议实现。

## 安全与运维要求

- Supabase 桶保持私有；浏览器上传和结果下载只使用短期签名 URL。
- 配置对象存储生命周期规则，自动删除 `payroll-inputs`、`payroll-outputs` 和 `payroll-task` 前缀下超过 14 天的数据。代码中的 `expiresAt` 只是任务过期标记，不会代替存储侧真实删除。
- `SUPABASE_SERVICE_ROLE_KEY` 只配置在 Vercel Environment Variables，绝不写入仓库、前端代码或日志。
- 监控函数耗时、超时率、内存峰值、上传耗时和对象存储错误。解析结果仍需按现有业务流程人工复核。

## 上线验收

1. 使用飞书企业账号登录，确认无 `overseas` 权限的用户收到 403，有权限用户可以进入页面。
2. 分别上传 1 MB、10 MB、接近 40 MB 的脱敏样本，确认浏览器请求中没有文件正文经过 Vercel API。
3. 对 8 个工具各跑至少一份代表性样本，记录 Function 总耗时和内存峰值；P95 必须明显低于 300 秒。
4. 中断一次上传，确认自动重试；弱网大文件场景若仍不可接受，再启用 TUS 可续传。
5. 确认下载 URL 过期后失效，并验证 14 天生命周期规则实际删除对象。
6. 人为制造解析错误，确认任务显示失败且日志中不包含文件正文、签名 URL 或服务角色密钥。
