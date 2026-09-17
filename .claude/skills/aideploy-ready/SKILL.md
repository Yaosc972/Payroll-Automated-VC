---
name: aideploy-ready
description: 让这个项目生而可部署：按 AIDeploy 接入契约写代码，交付前本地自检清零。 在本项目写代码、改 Dockerfile、加依赖或准备部署时遵循。
---

# AIDeploy 接入规范

让这个项目生而可部署：按 AIDeploy 接入契约写代码，交付前本地自检清零。

## 1. 动手前先问清楚

这几件事决定了项目结构，写完再改代价大。用户说不清时给推荐值并标注假设。

- 这个项目要部署到 AIDeploy 吗？（不部署就不必守下面的约束）
- 是单服务还是多服务组合（前端 / 后端 / worker / 定时任务）？
- 要用哪些依赖：数据库、缓存、对象存储、外部 API？
- 要不要登录？要不要初始数据（种子）？

## 2. 黄金路径产物（开发中同步产出，不是完成后再补）

齐了这些，平台零追问直达预览环境；缺了就得靠平台猜，猜错要来回改。

- `aideploy.json`（schema_version 2.0）：声明 services[]，运行形态取值 web、api、worker、scheduler、cron
- 每个构建单元一份 Dockerfile，配套 `.dockerignore`
- `.env.example`：把应用要读的环境变量列全（**只列名字，不写真值**）
- web/api 服务提供健康检查端点，并在 `health_check.path` 里声明它
- 需要建表/改表就自带迁移脚本，命令写进 `migration_command`

## 3. 环境变量纪律

配置从代码里分离、按标准名读取——这样同一份代码在各环境不用改一行。

- 依赖连接信息直接按标准变量名读，平台会注入：`DATABASE_URL`（postgresql）、`MYSQL_URL`（mysql）、`REDIS_URL`（redis）、`S3_ENDPOINT`（s3）、`AMQP_URL`（rabbitmq）、`<SERVICE>_BASE_URL`（external_api）
- 禁止自造连接变量名（`POSTGRES_DSN`、`DB_URL` 这类）——自造的平台不认，得多一轮映射确认
- 禁止自定义以 `AIDEPLOY_` 开头的变量：这是平台保留前缀，注入时会覆盖你的值
- 变量名表达「资源类型 + 用途」，别用 `HOST`、`PASSWORD`、`TOKEN` 这种无上下文的名字

## 4. Dockerfile 纪律

下面每一条平台准入都会检查，标「必须」的不满足会直接拦下部署。

- **必须**：改写成完整字面地址，例如 FROM python:3.12-slim；需要换源时用平台镜像代理前缀。（否则触发 `DOCKERFILE_FROM_VARIABLE`）
- **必须**：换用平台可信 registry，或加平台镜像代理前缀（devkit sync-platform-config 可写入）。（否则触发 `DOCKERFILE_FROM_UNREACHABLE`）
- **必须**：删除明文，改为运行期环境变量；密钥名进 aideploy.json 的 secrets 名单，值在平台密钥中心绑定。（否则触发 `DOCKERFILE_PLAINTEXT_SECRET`）
- 应当：固定版本，例如 python:3.12-slim。（生产制品按 digest 锁定，不受 tag 漂移影响）（否则触发 `DOCKERFILE_FROM_FLOATING_TAG`）
- 应当：改成监听 0.0.0.0，例如 uvicorn --host 0.0.0.0。（否则触发 `DOCKERFILE_LISTEN_LOCALHOST`）
- 应当：补 EXPOSE 并与 aideploy.json 的 services[].port 对齐（以 services[].port 为准）。（否则触发 `DOCKERFILE_EXPOSE_MISMATCH`）
- 应当：改成 exec 形式数组，例如 CMD ["node", "dist/main.js"]。（否则触发 `DOCKERFILE_NON_EXEC_CMD`）
- 应当：先 COPY 依赖清单（requirements.txt / package*.json / pom.xml）装依赖，再 COPY 源码。（否则触发 `DOCKERFILE_DEPS_LAYER_NOT_SPLIT`）
- 应当：生成 .dockerignore（devkit apply-fix 可一键写入）。（否则触发 `DOCKERFILE_NO_DOCKERIGNORE`）
- 应当：加非 root 用户，例如 RUN useradd -m app && USER app。（否则触发 `DOCKERFILE_ROOT_USER`）

## 5. 服务之间怎么互相调用

同一应用的服务独占一个命名空间，服务名就是主机名——多数情况零改码。

- 集群内互访用**裸名 DNS**：`http://api:8000`（`api` 即 services[].name）
- 需要更稳妥就读平台注入的：`AIDEPLOY_SVC_<NAME>_URL`、`AIDEPLOY_SVC_<NAME>_HOST`、`AIDEPLOY_SVC_<NAME>_PORT`
- 前端调后端用**相对路径** `/api`（同域按路由前缀分流）；禁止写死 `localhost:xxxx` 或某个环境的域名
- 应用自省信息平台也会注入：`AIDEPLOY_ENV`、`AIDEPLOY_APP`、`AIDEPLOY_SERVICE`、`AIDEPLOY_RELEASE_SEQ`、`AIDEPLOY_URL`
- nginx 之类用变量指向兄弟服务时，**必须**在 aideploy.json 的 env 里声明该变量，否则容器起来就 `host not found in upstream`

## 6. 数据库迁移纪律

平台按 应用×环境 给你开库并注入连接串，但**不理解也不代管表结构**——迁移自带。

- 用标准迁移工具（平台能自动识别的：`alembic`、`django`、`prisma`、`knex`、`knex`），把命令写进 `migration_command`
- 迁移必须**幂等**：重跑不炸（平台重试就是重跑一遍）
- **禁止运行时自动建表**（首次请求建表、手工进容器执行 SQL）——多副本与回滚下不可靠
- 迁移要向后兼容：平台回滚只回退代码与镜像，**不回退表结构**

## 7. 安全纪律

密钥只出现名字，值永远在平台密钥中心——这条是硬底线，违反直接阻断。

- 密钥不写进代码、Dockerfile、README、`aideploy.json` 的任何字面值
- 名字像密钥的变量（后缀 `_SECRET`、`_TOKEN`、`_PASSWORD`、`_KEY`）写进服务的 `secrets` 名单，值在平台绑定
- `.env` 不提交；给 `.env.example` 只留变量名
- 基础镜像用平台可信来源，`FROM` 写完整地址

## 8. 交付前必做

本地自检与平台准入用的是同一份规则——本地清零，平台基本就能过。

- 跑 `aideploy check`（或 MCP 工具 `aideploy_check`）
- 标 `✗` 的是**平台会拦下**的，逐条修到零；标 `!` 的是建议，尽量处理
- 修的是代码与接入信息本身，不要靠在平台页面上反复试错
- 没有 `aideploy.json` 就先跑 `aideploy gen-contract` 生成一份再核对

> 平台自己有一份完整说明：`https://hras-aideploy.ztn.cn/llms.txt`（目录与摘要）、`https://hras-aideploy.ztn.cn/llms-full.txt`（全文）。拿不准平台怎么用时读它，别猜。

> 本节由 aideploy devkit 依规则包 v3.0 生成，请勿手改；
> 重跑 `aideploy init` 即可更新。
