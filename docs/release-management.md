# 西格玛工作台发布与分支管理

本文用于固定西格玛工作台后续开发、集成、部署的边界，避免不同模块窗口互相覆盖生产环境。

## 结论

当前项目需要保留两条发布线：

- Vercel 生产线：面向当前公网试用环境，负责首页、后台管理、权限、已开放模块。
- 公司服务器生产线：面向 IT 部署的公司内网/服务器环境，负责公司部署栈适配。

模块开发分支不要直接部署生产。每个模块开发完成后，先在模块分支提交，再由发布整合分支选择性集成、测试、部署。

## 固定分支

| 用途 | 分支 | 说明 |
|---|---|---|
| Vercel 生产整合 | `codex/admin-module-release-consolidation` | 当前 Vercel 生产整合基线。只从这里部署 Vercel。 |
| 公司服务器整合 | `codex/admin-module-release-consolidation-platform` | IT 已改造的公司服务器部署线。后续公司服务器改动应优先基于这条线。 |
| 后台管理原型 | `codex/admin-management-console` | 后台管理早期原型来源，后续不应直接作为生产部署分支。 |
| 招聘奖金核算 | `codex/recruitment-bonus-workbench` | 招聘模块开发分支。 |
| 中国区正式工薪酬 | `codex/china-employee-payroll` | 正式工薪酬模块开发分支。 |
| 中国区外包工薪酬 | `codex/domestic-labor-payroll` | 外包工薪酬模块开发分支。当前生产默认不开放。 |
| FBU 美洲绩效奖金 | `codex/fbu-americas-performance-bonus` | FBU 模块开发分支。当前生产默认不开放。 |
| 海外劳务报账核对 | `codex/overseas-labor-worker-migration` / `codex/overseas-labor-async-storage` | 海外劳务模块历史开发线。集成时必须按具体 commit 选择，不要整分支硬合。 |

如后续新建更清晰的 Vercel 分支，可命名为：

```bash
codex/admin-module-release-consolidation-vercel
```

但在迁移完成前，仍以 `codex/admin-module-release-consolidation` 为当前 Vercel 基线。

## 模块状态规则

模块有三个独立状态，不要混在一起：

| 状态 | 含义 | 控制位置 |
|---|---|---|
| 代码是否已集成 | 模块代码是否已进入整合分支 | Git 分支/commit |
| 首页是否可见 | 首页是否展示模块卡片 | `bonus_platform/static/index.html`、模块配置、后台开关 |
| 用户是否能进入 | 用户角色是否有权限访问模块 | 后台权限、`permission-guard.js`、后端权限接口 |

允许出现以下状态：

- 代码已集成，但首页显示开发中。
- 首页可见，但无权限用户不能进入。
- 模块 UAT 试点，只给指定角色进入。
- 模块开发分支存在最新代码，但暂不进入 Vercel 生产线。

## 当前建议开放范围

Vercel 生产线建议保持：

- 首页：开放
- 后台管理：仅系统管理员开放
- 招聘奖金核算：开放给有权限用户
- 中国区正式工薪酬：按后台开关和角色开放
- 海外劳务报账核对：首页可见，状态 `UAT试点`，只给有权限用户使用
- 中国区外包工薪酬：不开放
- FBU 美洲绩效奖金：不开放

## 标准集成流程

模块开发窗口完成后，模块负责人先提交：

```bash
git status --short
git add <changed-files>
git commit -m "<module>: <summary>"
```

然后把以下信息交给整合窗口：

```text
模块：
分支：
commit：
目标：只集成但隐藏 / UAT 试点 / 正式开放
是否涉及共享文件：
是否需要环境变量：
是否需要数据库/Storage/Worker：
```

整合窗口执行：

```bash
git switch codex/admin-module-release-consolidation
git status --short
git fetch --all --prune
```

优先用 cherry-pick 或按文件选择性引入：

```bash
git cherry-pick <commit>
```

如果冲突集中在共享文件，必须人工检查，不要直接用某一边覆盖。

## 共享文件高风险清单

这些文件经常被多个模块同时改动，集成时必须逐行看：

- `bonus_platform/app.py`
- `bonus_platform/static/index.html`
- `bonus_platform/static/styles.css`
- `bonus_platform/static/permission-guard.js`
- `bonus_platform/static/admin.html`
- `bonus_platform/static/admin.js`
- `bonus_platform/static/release-info.json`
- `vercel.json`
- `requirements.txt`
- `render.yaml`
- `docs/vercel-supabase-deployment.md`

共享文件冲突处理原则：

- 保留后台管理、权限、飞书登录、生产开关的现有逻辑。
- 模块入口只新增或调整对应模块，不顺手重排其他模块。
- 未开放模块不能因为合代码变成可进入。
- `release-info.json` 要准确标记当前生产来源分支。
- Vercel 配置和公司服务器配置不要互相覆盖。

## Vercel 发布检查

部署前必须确认：

```bash
git branch --show-current
git status --short
python3 -m pytest
```

如果只改文档，可以不跑全量测试，但发布生产前仍建议跑。

部署命令：

```bash
vercel deploy --prod -y --no-wait --scope yaosc-s-project
```

部署后确认：

```bash
vercel inspect <deployment-url> --scope yaosc-s-project
```

线上至少验证：

- `https://sigma-workbench.vercel.app/`
- `https://sigma-workbench.vercel.app/recruitment.html`
- `https://sigma-workbench.vercel.app/admin.html`
- `https://sigma-workbench.vercel.app/china-employee-payroll.html`
- `https://sigma-workbench.vercel.app/overseas-labor.html`

验证重点：

- 首页模块状态正确。
- 无权限用户不能进后台。
- 系统管理员可以进后台。
- 已关闭模块不能进入。
- UAT 模块只对有权限用户开放。
- 上传、核算、导出必须用真实材料做端到端验证，不能只看页面能打开。

## 公司服务器发布线

公司服务器部署线以：

```bash
origin/codex/admin-module-release-consolidation-platform
```

为基线。

这条线可能包含 IT 对部署栈、路径、存储、反向代理、认证入口的改造。不要把 Vercel 分支整条覆盖到公司服务器分支。

公司服务器需要新功能时，建议流程是：

1. 从公司服务器分支创建集成分支。
2. 只 cherry-pick 已确认稳定的业务 commit。
3. 手工处理部署栈差异。
4. 由 IT 在公司环境验证。

## 不能做的事

- 不要从模块开发分支直接 `vercel deploy --prod`。
- 不要把 FBU、外包工薪酬这类未开放模块顺手开放。
- 不要为了修一个模块直接覆盖 `app.py`、`index.html`、`permission-guard.js`。
- 不要在 Vercel 分支里硬塞公司服务器专用配置。
- 不要在公司服务器分支里硬塞 Vercel worker 过渡方案。
- 不要把本地 `.env`、密钥、数据库连接串提交到仓库。

## 建议的交付格式

以后模块窗口交付时，按这个格式发给整合窗口：

```text
模块开发完成，准备集成。

模块：
分支：
commit：
目标开放状态：
需要权限角色：
涉及共享文件：
新增环境变量：
验证结果：
风险：
```

整合窗口完成后，输出：

```text
已集成 commit：
当前整合分支：
测试结果：
部署链接：
线上验证结果：
未验证风险：
下一步：
```
