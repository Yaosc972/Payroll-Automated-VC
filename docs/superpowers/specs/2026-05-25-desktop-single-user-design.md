# 西格玛工作台桌面单机版设计规格

## 目标

把当前本地 Web 版招聘奖金核算平台封装为 Windows 10+ 和 macOS 可运行的桌面应用。第一版采用完全本地单机模式，所有薪酬数据、上传文件、核算结果、规则库和批次索引都保存在用户本机。

## 范围

第一版只解决“普通用户双击打开并本地核算”的问题：

- 桌面应用启动后自动启动本地 FastAPI 计算服务。
- 前端继续复用当前 Command Center 页面。
- 计算逻辑继续复用 `bonus_platform/engine/`。
- 批次元数据写入 SQLite，同时保留每个批次目录下的 `metadata.json` 作为文件级追溯。
- 上传 Excel、初算结果、待确认表、最终结果、差异报告继续以文件形式保存。
- 不做账号、权限、云同步、多人协作、自动更新和企业 SSO。

## 架构

```text
Σ-Workbench 桌面应用
├── Electron 主进程
│   ├── 创建桌面窗口
│   ├── 启动内置 Python/FastAPI 后端
│   └── 关闭应用时停止后端
├── FastAPI 后端
│   ├── 现有 API
│   ├── 计算引擎
│   ├── Excel 读写
│   └── SQLite 批次索引
├── 静态前端
│   └── 当前 Command Center 页面
└── 本地数据目录
    ├── sigma_workbench.db
    ├── rules/
    ├── uploads/
    ├── runs/
    ├── exports/
    └── logs/
```

## 本地数据目录

开发环境默认继续使用项目内 `outputs/`，避免破坏现有测试和调试习惯。

桌面应用启动时由 Electron 设置 `SIGMA_WORKBENCH_HOME`，指向系统应用数据目录：

- Windows: `%APPDATA%/SigmaWorkbench`
- macOS: `~/Library/Application Support/SigmaWorkbench`

Python 后端读取该环境变量后，将规则库、导出文件、批次目录和 SQLite 数据库都放在该目录下。

## SQLite 表设计

第一版只建立批次索引表，保持简单：

```sql
CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  month INTEGER NOT NULL,
  status TEXT NOT NULL,
  source_filename TEXT,
  recruitment_total REAL DEFAULT 0,
  referral_total REAL DEFAULT 0,
  exception_count INTEGER DEFAULT 0,
  pending_count INTEGER DEFAULT 0,
  pending_total REAL DEFAULT 0,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

SQLite 是索引层，不替代 Excel 文件。完整批次仍保存在 `runs/<run_id>/`。

## 数据流

1. 用户打开桌面应用。
2. Electron 创建本地数据目录并设置 `SIGMA_WORKBENCH_HOME`。
3. Electron 启动 Python/FastAPI 服务。
4. 页面访问 `http://127.0.0.1:<port>`。
5. 用户上传月度 Excel。
6. 后端读取规则库并计算。
7. 后端保存批次目录、结果 Excel、`metadata.json`、`table_rows.json`。
8. 后端将批次摘要写入 SQLite。
9. 用户重启应用后，首页通过 SQLite/文件元数据恢复批次列表。

## 错误处理

- 后端启动失败：Electron 显示本地错误页，提示查看日志。
- 端口占用：Electron 选择可用端口并通过环境变量传给前端 URL。
- 数据目录不可写：启动时阻断，提示用户更换目录或检查权限。
- SQLite 损坏：保留批次目录为事实来源，后续可增加重建索引功能。

## 测试策略

- 单元测试：验证 `SIGMA_WORKBENCH_HOME` 能切换数据目录。
- 单元测试：验证保存批次后 SQLite 有对应索引。
- API 回归：现有批次计算、最终确认、差异报告接口继续通过。
- 桌面 smoke test：验证 Electron 可启动后端并加载首页。

## 验收标准

- Windows/macOS 用户无需安装 Python 即可打开应用。
- 应用内完整完成上传、初算、待确认、最终导出、差异检验。
- 重启应用后能看到历史批次。
- 所有数据默认保存在本机应用数据目录。
- 现有奖金计算测试不因桌面化改造发生结果变化。
