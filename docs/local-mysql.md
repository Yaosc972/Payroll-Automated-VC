# 本机 MySQL 单机运行

本配置用于本地功能迁移和回归，不连接当前 Vercel 生产环境、Supabase、公司 MySQL 或 OBS。

## 运行边界

本机当前验收使用 `http://localhost:8002`（以下启动示例中的 8001 可替换为 8002，飞书回调地址须同步匹配）。独立开发分支为 `codex/local-mysql-migration`；提交源码不代表全部迁移验收完成，也不代表发布生产。

### 2026-09-20 交付说明

- `.env.local.mysql`、本机 MySQL 数据、业务上传文件、飞书凭据和安装包不进入 Git。
- 本地下载目录已配置 Mac 0.3.16 重打包 DMG 和从飞书找回的 Windows 0.3.16 原包；它们位于本机数据目录，克隆源码不会自动获得安装包。Mac 重打包不等同于历史 CI 原包。
- 独立性审计仍有待处理项：社保连接器目录缺少模板字典/报盘桥接所需的 `lib/spreadsheet-io.mjs`；模板路径等需按新机器配置；海外劳务材料工具仍有个人目录默认值；FBU 展示页仍有旧 Vercel 站点链接。北森同步成功不能替代模板报盘链路验收。

- 应用：本机 FastAPI，浏览器访问 `http://127.0.0.1:8001`。
- 数据库：本机 MySQL 8.0，建议使用独立端口 `3307`，避免覆盖已有 MySQL 服务。
- 文件：`SIGMA_WORKBENCH_HOME` 指定的本地目录。
- 北森：本地 Node 连接器直连北森实时任职记录；不配置远程 Vercel 连接器。
- 长任务：本机进程或本地 Worker，不使用 Vercel Function/Cron。

## 准备 MySQL

本机已有其他 MySQL 实例时不要停用或覆盖它。建议安装 MySQL 8.0，并使用独立数据目录、端口和服务账号：

```bash
brew install mysql@8.0

# 首次初始化时使用独立数据目录；已存在的本机 MySQL 数据目录不要复用。
# 把下面路径中的用户名替换成本机 macOS 用户名。
MYSQL80_PREFIX="$(brew --prefix mysql@8.0)"
MYSQL80_DATA="/Users/<本机用户名>/Library/Application Support/SigmaWorkbench/mysql80-data"
MYSQL80_SOCKET="/tmp/sigma-workbench-mysql80.sock"
mkdir -p "$MYSQL80_DATA"

# 只在这个目录为空且尚未初始化时执行一次：
"$MYSQL80_PREFIX/bin/mysqld" --no-defaults --initialize-insecure \
  --basedir="$MYSQL80_PREFIX" --datadir="$MYSQL80_DATA" \
  --log-error="$MYSQL80_DATA/init.log"

# 启动本机独立实例；不要使用 brew services start mysql@8.0，避免和
# 其他 MySQL 服务共用默认数据目录或 3306 端口。
"$MYSQL80_PREFIX/bin/mysqld" --no-defaults --daemonize \
  --basedir="$MYSQL80_PREFIX" --datadir="$MYSQL80_DATA" \
  --port=3307 --socket="$MYSQL80_SOCKET" \
  --pid-file="$MYSQL80_DATA/mysqld.pid" \
  --log-error="$MYSQL80_DATA/mysqld.log" \
  --bind-address=127.0.0.1 --skip-name-resolve

# 验证：
"$MYSQL80_PREFIX/bin/mysqladmin" --protocol=socket \
  --socket="$MYSQL80_SOCKET" -u root ping
```

数据库初始化只针对本地实例执行：

```sql
CREATE DATABASE sigma_workbench_local
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER 'sigma_app'@'127.0.0.1'
  IDENTIFIED BY 'replace-with-a-random-local-password';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON sigma_workbench_local.* TO 'sigma_app'@'127.0.0.1';
```

运行账号只用于本地应用；表结构初始化或迁移应使用单独的迁移账号。不要把密码写入 Git、前端资源或 Electron 安装包。

## 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

cp env.local.mysql.example .env.local.mysql
# Edit .env.local.mysql: fill the local database password, data root, and
# any local Beisen engine paths needed by the social-insurance module.
set -a
source .env.local.mysql
set +a

python3 -m uvicorn bonus_platform.app:app --reload --host 127.0.0.1 --port 8001
```

当前本地模式的业务文件仍保存到 `SIGMA_WORKBENCH_HOME`，MySQL 保存管理、权限和批次元数据。后续将按模块补齐 MySQL 状态表；不能用“能连上 MySQL”代替业务回归。

## 验收顺序

### 核对助手安装包

`SIGMA_LABOR_STATE_BACKEND=local` 且未启用云存储时，管理员安装包上传、发布清单及下载使用数据目录下的 `worker-releases/`，不访问 Blob / Supabase。上传验证实际大小与 SHA-256，发布时再次核验；同版本文件不可覆盖。下载保留现有登录权限检查。

沿用现有发布协议：macOS ARM64 的 DMG 和 Windows x64 的 EXE 必须版本一致并均上传完成，才正式发布。只有源码、没有安装包时仍显示“待发布”，不能以测试文件代替正式安装包。此迁移保留现有 `sha256:` 校验字段，不代表新增了操作系统代码签名。

### 业务验收

1. 应用启动后检查 `/api/health`、管理员权限和会话。
2. 招聘奖金：上传、核算、确认、导出、重启后恢复。
3. 正式工和国内劳务：Excel 上传、批次状态、配置、导出和历史恢复。
4. FBU 和海外劳务：多文件上传、Worker、失败重试、报告下载和重启恢复。
5. 社保：本地北森主体同步、实时离职规则上下文、模板上传、名单确认、报盘包和本地预热任务。正常使用不需要每月手工导出离职文件；旧 `mvp.mjs` 引擎仅作为兼容回退。
6. 管理后台：飞书登录、通讯录同步、角色权限、公告、反馈和审计。
7. 删除或修改本地 MySQL/文件目录前，先确认回归数据不再需要；本地测试不得指向生产数据。
