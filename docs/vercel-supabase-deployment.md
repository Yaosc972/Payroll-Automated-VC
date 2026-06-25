# Vercel + Supabase 部署说明

## 环境分层

本地开发环境继续使用默认配置，不需要公网链接：

```bash
python3 -m uvicorn bonus_platform.app:app --reload
```

本地默认使用 `outputs/sigma_workbench.db` 保存后台权限草稿。正式环境通过 Vercel 环境变量连接 Supabase Postgres，不会影响本地开发数据。

## 正式环境当前开放范围

当前正式环境只开放：

- 首页
- 招聘奖金核算
- 后台管理

以下模块仍保持开发中，默认关闭：

- 中国区正式工薪酬核算
- 中国区外包工薪酬核算
- FBU美洲绩效奖金核算
- 海外劳务报账核对

后续某个模块达到可运行状态后，由系统管理员在后台管理里打开模块开关，并给对应模块管理员授权。

## Vercel 环境变量

生产环境必须配置：

```text
ADMIN_DATABASE_URL=postgresql://...
SESSION_COOKIE_SECURE=true
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_REDIRECT_URI=https://你的-vercel域名/api/auth/feishu/callback
FEISHU_AUTH_URL=https://open.feishu.cn/open-apis/authen/v1/index
```

如果还没有接真实飞书登录，可以先不配置 `FEISHU_APP_SECRET`，但正式登录会不可用。

## Supabase

在 Supabase 创建项目后，从数据库连接信息里复制 Postgres pooled connection string，填入 Vercel 的 `ADMIN_DATABASE_URL`。

建议使用 pooled 连接串，适配 Vercel serverless 短连接场景。

## 上传文件与运行文件

Vercel serverless 不适合把上传文件长期保存在本机文件系统。当前线上运行时会把临时文件写入 `/tmp/sigma_workbench`。

后续接入 Supabase Storage 后，建议执行以下保留策略：

- 上传临时文件：7 天
- 导出文件：30 天
- 失败任务文件：7 天
- 普通操作日志：365 天
- 权限变更日志：至少 3 年或永久保留

## 海外劳务后台 Worker

海外劳务报账核对的 PDF/Excel 核对不应在 Vercel Function 内执行。生产环境采用：

- Vercel：页面、短 API、创建批次、签发上传地址、登记文件、提交任务、查询状态
- Supabase Storage：保存 PDF、Excel 和报告文件
- Supabase Postgres：保存 `labor_jobs` 后台任务队列
- 独立 Worker：下载文件、核对、生成报告、回写状态

Vercel 生产环境需要额外配置：

```text
SIGMA_OVERSEAS_LABOR_ACCESS=production
SIGMA_LABOR_STORAGE_BACKEND=supabase
SIGMA_LABOR_EXECUTION_MODE=worker
SIGMA_LABOR_JOB_BACKEND=postgres
SUPABASE_URL=https://你的项目id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SIGMA_LABOR_SUPABASE_BUCKET=sigma-labor-runs
ADMIN_DATABASE_URL=postgresql://...
```

当前 0 元过渡方案是用本地电脑运行 Worker。先复制模板并填入生产 Supabase/AI 密钥：

```bash
cp docs/env.worker.local.example .env.worker.local
```

启动前自检：

```bash
scripts/check-local-labor-worker.sh
```

自检通过后启动本地 Worker：

```bash
scripts/start-local-labor-worker.sh
```

如果后续改用付费或云端 Worker，启动命令仍是：

```bash
python3 -m bonus_platform.worker.main --require-ready --interval 5 --worker-id overseas-labor-1
```

上线前检查：

```bash
curl https://sigma-workbench.vercel.app/api/labor/storage-health
curl https://sigma-workbench.vercel.app/api/labor/worker-health
```

需要探测 Supabase/Postgres 连通性时使用：

```bash
curl "https://sigma-workbench.vercel.app/api/labor/storage-health?probe=1"
curl "https://sigma-workbench.vercel.app/api/labor/worker-health?probe=1"
```

如果 `/api/labor/worker-health` 返回 `LABOR_WORKER_QUEUE_UNAVAILABLE`，说明 Vercel 已进入 Worker 模式但没有可持久化的 Postgres 队列配置，海外劳务任务会停留在“待处理”。

本地 Worker 和 Render Background Worker 的详细步骤见 `docs/overseas-labor-worker-runbook.md`。Render Background Worker 模板在仓库根目录 `render.yaml`，但它是付费备选，不是当前默认方案。

## 部署命令

本机完成 Vercel 登录后：

```bash
vercel link
vercel env add ADMIN_DATABASE_URL production
vercel env add SESSION_COOKIE_SECURE production
vercel env add FEISHU_APP_ID production
vercel env add FEISHU_APP_SECRET production
vercel env add FEISHU_REDIRECT_URI production
vercel env add FEISHU_AUTH_URL production
vercel deploy --prod
```

如果使用 GitHub 集成，后续可以改为推送主分支自动部署。
