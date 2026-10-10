# 国内劳务补充模板与 SkillHub 双线集成 — 2026-10-10

本次仅本地集成，没有推送、部署、数据库迁移或生产配置变更。

## 来源与目标

只 cherry-pick `65b4cbc3469f04a7fb1405465ef18e9052264705`（`feat(domestic-labor): add supplemental templates and SkillHub`），未整合来源分支其他提交。

| 目标 | 集成前 HEAD | 本次 cherry-pick |
|---|---|---|
| `codex/domestic-production-20260909` | `64ae840a` | `78fcf366` |
| `codex/company-feature-integration-20261009`（公司 MySQL/OBS 发布线） | `6ad511c2` | `86e09cf1` |

开始前 fetch 核实：GitHub Vercel 远端为 `c9113e5e`，本地另有未发布正式工提交及未提交适配；GitLab `master` 为 `6ad511c2`，与公司集成基线一致。两条目标没有本次等价提交；共享班次配置、九个夜班班次和东南 B2B 工龄奖已有等价改动，不重复集成。

## 冲突与保留

- 两条线保留现有反馈组件缓存版本 `20260916-01`，加入 Skill 上新脚本及新国内劳务脚本版本。
- 夜班导出测试按实际班次基线数量和编号验证，保留 152 条公司/生产班次。
- 高温入口测试采用现有按钮语义，继续保护核算页“验证中”状态。
- 公司 `AGENTS.md` 同时保留 AIDeploy 规范和新增 SkillHub 发布规则。
- 公司 JavaScript 保留 `/api/domestic-labor/upload-mode` 的后端上传分流；将网点映射和空名单确认传给 multipart 请求，不丢失重试确认。新增前端及 OBS 流程回归保护该冲突处理。
- 公司 MySQL/OBS adapter、权限脚本、认证、`aideploy.json`、Dockerfile 和 `vercel.json` 与本次前基线无差异。新 SkillHub 页面和 API 沿用国内模块权限。
- `scripts/domestic_labor_local_preview.py` 只用于本地；未写入任何生产启动或部署配置。

来源的未提交“反馈与更新”导航和旧交接文件逐文件 SHA-256 核对未改变。Vercel 正式工草稿暂存后恢复：所有其他原文件 SHA-256 一致，`app.py` 原草稿补丁除位置偏移外完全一致。临时 stash 已移除。

## 检查结果

两条线分别执行用户指定的五文件 pytest：各 **346 passed**。指定三文件 Node：Vercel **21 passed**，公司 **22 passed**（新增一项公司后端上传确认传参回归）。

两条线分别运行 `python3 -m scripts.domestic_labor_skillhub_release`：7 份 Skill、7 条上新记录；发布清单无变更，未重复上新。所有国内劳务 JS `node --check` 及 `git diff --check` 通过。

公司追加：存储 adapter、安全前端、国内持久化及夜班配置 **67 passed**；公司安全 API **74 passed**；公司 OBS 新资料完整流程 **1 passed**；夜班缺失配置及各模块刷新导航 Node **16 passed**。Vercel 夜班缺失配置 Node **7 passed**。

OBS 专项使用真实国内存储适配代码及模拟 OBS 底层，验证合成 Excel 经后端上传、名称映射、空名单确认、13.8 元高温核算、清空本地缓存后恢复、中文 Excel 导出及再次恢复下载。没有访问真实公司 MySQL 或 OBS；不能作为生产业务验收。

## 页面复查

使用 ego-browser，在两个目标代码的独立 loopback 预览中验证。公司预览 `8006`、Vercel 预览 `8007`，不改动原先占用 `8002` 的服务。

- 两条线：默认 2026-09；七份 Skill 上新提示；152 条夜班基线、调整弹窗打开和关闭；SkillHub 七份目录、使用指引、单包下载 SHA-256 一致。
- 公司：编辑正班时数后显示“1 条修改未保存”；指引切换到高温并显示不享有名单要求，刷新恢复科目和月份；进入 SkillHub 后上新提醒已读且返回保持隐藏。
- 公司实际总包下载含七份 ZIP，逐一 SHA-256 与发布清单一致；独立 Skill 的运行及核算由指定 pytest 覆盖。

页面预览使用独立本地数据和测试会话，没有生产登录或真实材料写入。预览服务、浏览器任务和本次无须保留的临时下载已在收尾清理；本地发布脚本导出的七份 Skill 和总包保留在各工作区 `outputs/domestic-skillhub-latest/`。
