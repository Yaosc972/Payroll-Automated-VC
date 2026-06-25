# 海外劳务报账 Worker 部署运行手册

## 目标

生产环境的海外劳务报账核对拆成两层：

- Vercel：页面、登录、权限、创建批次、签发 Supabase 上传地址、登记文件、创建任务、查询状态。
- 独立 Worker：从 Supabase Storage 下载 PDF/Excel，执行核对，生成报告，再上传回 Supabase Storage。

这样可以避开 Vercel Function 的请求体、执行时长和后台线程限制。Vercel 继续承载首页、招聘奖金、后台管理、中国区正式工薪酬等短请求模块。

## 已有生产前提

Vercel 生产环境需要具备：

```text
SIGMA_OVERSEAS_LABOR_ACCESS=production
SIGMA_LABOR_STORAGE_BACKEND=supabase
SIGMA_LABOR_STORAGE_ENV=production
SIGMA_LABOR_SUPABASE_BUCKET=sigma-labor-runs
ADMIN_DATABASE_URL=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

建议同时补充显式队列配置：

```text
SIGMA_LABOR_EXECUTION_MODE=worker
SIGMA_LABOR_JOB_BACKEND=postgres
```

线上健康检查：

```bash
curl "https://sigma-workbench.vercel.app/api/labor/storage-health?probe=1"
curl "https://sigma-workbench.vercel.app/api/labor/worker-health?probe=1"
```

两个接口都应返回 `ok: true`。

## 本地电脑 Worker（当前 0 元方案）

本地电脑 Worker 的作用是：连接生产 Supabase，读取 `labor_jobs` 队列，下载生产上传的文件，执行核对，再把报告写回生产 Supabase。

准备本地环境变量：

```bash
cp docs/env.worker.local.example .env.worker.local
```

然后编辑 `.env.worker.local`，填入：

```text
ADMIN_DATABASE_URL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
MIMO_API_KEY
```

`.env.worker.local` 会被 `.env*` 忽略，不会提交到 git。

启动前自检：

```bash
scripts/check-local-labor-worker.sh
```

自检通过后启动常驻 Worker：

```bash
scripts/start-local-labor-worker.sh
```

终端保持打开时，Worker 会每 5 秒读取一次生产队列。关闭终端或电脑休眠后，海外劳务任务会继续留在队列里，但不会被处理；下次重新启动 Worker 后会继续消费。

只想处理一个排队任务时可以直接运行：

```bash
scripts/start-local-labor-worker.sh --once
```

如果需要自定义 Worker 名称：

```bash
SIGMA_WORKER_ID=local-overseas-labor-mac scripts/start-local-labor-worker.sh
```

## Render Background Worker（付费备选）

仓库里已提供 `render.yaml`。在 Render 中创建 Blueprint 或 Background Worker 后，使用同一份代码，启动命令为：

```bash
python3 -m bonus_platform.worker.main --require-ready --interval 5 --worker-id render-overseas-labor-1
```

上线前自检命令：

```bash
python3 -m bonus_platform.worker.main --check --probe
```

自检会检查：

- Supabase Storage 是否启用、bucket 是否可写；
- Postgres `labor_jobs` 队列是否可用；
- AI/OCR 配置是否完整；
- 输出不会包含数据库连接串、service role key 或 AI key。

### Render 必填环境变量

```text
SIGMA_WORKBENCH_HOME=/tmp/sigma-workbench
SIGMA_OVERSEAS_LABOR_ACCESS=production
SIGMA_LABOR_STORAGE_BACKEND=supabase
SIGMA_LABOR_STORAGE_ENV=production
SIGMA_LABOR_SUPABASE_BUCKET=sigma-labor-runs
SIGMA_LABOR_EXECUTION_MODE=worker
SIGMA_LABOR_JOB_BACKEND=postgres
ADMIN_DATABASE_URL=Supabase pooled Postgres connection string
SUPABASE_URL=https://你的项目id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=Supabase service_role key
AI_ENABLED=true
AI_PROVIDER=mimo
MIMO_API_KEY=你的 MiMo API key
AI_TIMEOUT_SECONDS=180
AI_DOCUMENT_TOOLCHAIN=pypdfium2,mimo
PARALLEL_MAX_WORKERS=1
PARALLEL_IMAGE_RENDER_WORKERS=1
```

`ADMIN_DATABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`MIMO_API_KEY` 必须只填在 Render 环境变量里，不要提交到代码。

## 手动验证 Worker

如果本地有完整生产同等环境变量，可以先跑一次自检：

```bash
python3 -m bonus_platform.worker.main --check --probe
```

只处理一个排队任务：

```bash
python3 -m bonus_platform.worker.main --once --worker-id local-test-worker
```

持续轮询：

```bash
python3 -m bonus_platform.worker.main --require-ready --interval 5 --worker-id local-worker
```

## 验证路径

1. 打开生产海外劳务页面，新建批次。
2. 上传 PDF 发票和 Excel 账单。
3. 完成字段映射。
4. 点击生成核对报告。
5. 前端应进入排队/处理中状态，而不是在当前 Vercel 请求里等待十几分钟。
6. Worker 日志应出现领取任务、心跳、生成报告或失败重试。
7. 前端轮询批次状态，完成后展示识别结果和报告下载入口。

## 故障判断

- `/api/labor/worker-health` 不是 `ok: true`：队列配置或数据库连接有问题。
- Worker 自检 Storage 失败：Supabase URL、service role key、bucket 或网络有问题。
- Worker 领取不到任务：检查 `SIGMA_LABOR_EXECUTION_MODE=worker`、`SIGMA_LABOR_JOB_BACKEND=postgres`，以及 Vercel 是否成功创建 `labor_jobs`。
- 任务反复 `retry_wait`：查看 Worker 日志中的最近错误，通常是 Storage 网络、AI 超时或输入文件问题。
- 任务一直 `running`：检查 Worker 是否还活着；租约过期后下一个 Worker 会自动回收重跑。
