# HRAS 薪酬核算工作台

HRAS 薪酬核算工作台是一套面向薪酬与共享服务团队的企业薪酬自动化平台。它将规则维护、材料上传、字段校验、确定性核算、异常复核和结果导出组织在同一工作台中。

生产环境：[sigma-workbench.vercel.app](https://sigma-workbench.vercel.app/)

> 核算金额由版本化业务规则和确定性计算引擎生成，不由生成式 AI 决定。生产环境的模块入口和数据范围受登录账号及角色权限控制。

## 主要能力

| 业务域 | 工作台能力 |
| --- | --- |
| 全球招聘奖金 | 招聘奖金与内推奖金核算、规则校验和结果导出 |
| 中国区正式工薪酬 | 正式工薪酬相关科目的材料处理与核算 |
| 中国区外包工薪酬 | 七类补贴与奖金核算、规则包、活动记录和计算明细 |
| 海外薪酬 | FBU 美洲绩效奖金与海外薪资核算 |
| 海外劳务 | 报账材料识别、差异核对和异步任务恢复 |
| 社保报盘 | 主体名单查看、确认、审核清单和报盘文件处理 |
| 平台管理 | 飞书登录、组织同步、角色权限、功能公告与反馈 |

不同环境和账号可见的模块可能不同，以平台权限配置为准。

## 工作方式

典型核算流程为：

1. 选择业务模块和核算周期。
2. 上传 Excel、PDF 等业务材料。
3. 检查工作表用途、字段完整性和需要人工确认的规则。
4. 使用当前规则版本执行核算。
5. 复核异常、计算依据和逐人明细。
6. 导出可追溯的核算结果。

## 技术架构

- 后端：Python 3.11、FastAPI。
- 前端：原生 HTML、CSS、JavaScript，按业务模块拆分。
- 文件处理：Excel、PDF 解析及模块化规则引擎。
- 生产部署：Vercel Functions 与静态资源。
- 持久化：按环境配置的 Supabase/PostgreSQL 与对象存储。
- 身份与权限：飞书登录、组织身份和模块级角色授权。
- 桌面能力：部分劳务处理流程提供 Electron/Worker 构建。

## 本地开发

建议使用 Python 3.11：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt pytest
python3 -m uvicorn bonus_platform.app:app --reload --port 8001
```

浏览器访问：

```text
http://127.0.0.1:8001/
```

运行测试：

```bash
python3 -m pytest -q
node --test tests/*.test.cjs
```

## 仓库与发布

- `main`：默认分支，保存已验证并同步公开的稳定代码。
- `codex/domestic-production-20260909`：当前 Vercel 生产整合与发布分支。
- `codex/*`：模块开发、问题修复和阶段性交付分支。

模块分支不能直接覆盖生产。功能先在模块分支完成，再选择性集成到生产发布线；生产验证通过后同步 `main`。详细规则见 [发布与分支管理](docs/release-management.md)。

## 数据与安全

- 不要提交真实薪酬材料、人员名单、导出结果或本地核算数据。
- 不要提交 `.env`、访问令牌、服务账号密钥或数据库连接信息。
- 测试和演示数据必须使用明确标记的合成内容。
- 调整登录、权限、存储或生产部署配置时，需要单独验证并保留回滚点。

## 目录概览

```text
bonus_platform/       FastAPI 应用、业务引擎与工作台前端
tests/                Python 与 Node.js 自动化测试
docs/                 发布、部署和业务交接文档
tools/                验证、回归与发布辅助工具
desktop/              桌面端封装
labor-worker-desktop/ 劳务 Worker 桌面构建
```
