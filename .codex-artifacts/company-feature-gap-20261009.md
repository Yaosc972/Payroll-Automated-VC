# 公司发布线功能差异盘点 — 2026-10-09

本次只读核对仓库与代码，没有集成、推送或部署。此前中国正式工 Vercel 发布暂停决定继续生效。

## 核查基线

- 公司仓库：`https://git.eminxing.com/zt27532/hras-global-payroll-workbench.git`。
- 重新 fetch 并通过 ls-remote 核实：`gitlab/master = 0d1411ceb605eacbac83e6fcbea9d1cde2cd822e`，2026-10-03 安全整改提交。
- 公司配置：AIDeploy `payroll-automated-vc`，FastAPI 常驻容器、MySQL、OBS；保留 Dockerfile、aideploy.json、MySQL/OBS 接口及安全整改。
- Vercel 已发布代码比较基线：`origin/codex/domestic-production-20260909 = c9113e5ef00230f1818359c1c180e2f478d65520`。
- 正式工新功能来源：本机 `cca1f001e963c53ace2c82eb5cee9aef13c5c495`，尚未进入公司 master；Vercel 本机整合提交为 `64ae840a`，未发布。
- 公司 `/api/health` 和 AIDeploy 首页当前均 HTTP 200。健康响应只证明服务可达，未取得线上 release/source commit/image digest，不能断言线上镜像就是远端 master。
- 旧 release-management.md 仍提及早期公司平台分支；较新的公司安全方案指定 GitLab master，当前远端 master 与该公司代码线一致。本次以已核实 GitLab master 为比较对象。

## 已在平台生产线、尚未进入公司 master 的功能

| 功能 | 来源提交 | 公司代码缺口 | 公司适配要求 |
|---|---|---|---|
| 首页新版布局与官方 HR 政策资讯 | `637a5e40`, `460fff8b`, `a4fe0db2` | 缺政策采集后端、来源配置、资讯抽屉；首页布局和窄屏适配较旧 | 保留公司权限与首页模块范围；通过现有 MySQL adapter 迁移 policy_articles/policy_source_checks；采集调度接公司环境，不能复制 Vercel Cron 配置 |
| 模块刷新保持位置、Windows HarmonyOS 字体 | `cb45d53c` | 招聘当前批次、外包当前视图、FBU 活动/步骤及社保视图刷新恢复较旧；缺字体资源与授权页 | 选择性集成前端与资源，保留公司权限保护和 OBS 上传流程 |
| 夜班配置及交互 | `2971abdc`, `9f4f0f6b`, `9efcc5be`, `9e904cc6` | 基础班次公司 143 条、平台 152 条；缺 LB68/LB69/LB70/LB71/LB35/HD060/HD061/DN29/DN30；缺弹窗作用域修复和跨月共享配置 | 保留 OBS 持久化；验证共享配置、旧月度配置、历史修订与合法用户范围 |
| 东南 B2B 工龄奖 | `0f563336` | gonglingjiang 缺“东南B2B枢纽组”部门与岗位映射；规则说明仍较旧 | 同步引擎与规则说明，按同份月考勤核对金额 |
| 社保审批中离职与月初离职规则 | `bd49877d` | 公司规则版本仍 `2026.09.10-01`，缺候选人员全部审批状态离职检查和同月 1～14 日自愿/非自愿停保判断；缺新增人工确认边界 | Python 快照重算与 Node 连接器必须配套；保留公司本地连接器、北森凭据入口及禁用最终政府申报范围 |
| 社保并发历史恢复修复 | `644d12a3`，相关测试 `aa30bb7c` | 仍用固定 `.restore.tmp`，并发恢复可能互相覆盖/抢占 | 仅引入唯一临时文件名与 finally 清理，保留 OBS 分支；不整文件覆盖 |

## 新模块已提交，但尚未完成生产交付

`cca1f001` 的集团餐补按月自动读北森、WX Excel、ABU 核算月组织搬迁补贴、统一独立活动、创建人及头像、确认/进度/导出交互、中文双工作表，均未进入公司 master。

公司原有餐补计算引擎与 Vercel 已发布版本相同，深圳正常班、LBU BI、首打卡异常规则不是缺失项。新增活动/任务实现不能直接以临时 JSON 与进程内后台任务上线。公司应另作 MySQL 活动/任务持久化、OBS 源数据与结果保存、可靠任务执行、服务端飞书身份及北森凭据适配；保留 `0d1411ce` 鉴权整改。

Vercel 暂存适配中的 PostgreSQL 两表及 Supabase 后端开关不能原样用于公司 MySQL；公司代码配置使用 OBS，不因 Vercel 的 Supabase Storage 402 自动受阻。真实公司 OBS 配置和读写仍需独立验证。

## 本机未提交改动，尚不是可直接发布的交付

原开发目录 `/Users/zt27532/Documents/New project 2`：

- 海外劳务：仓库号文件名识别、仓库冲突下的付款总额与分仓分配区分、Voyage 明细结构识别、供应商草案状态、相应测试与页面显示。
- FBU：旧 runs JSON 的额外字段兼容过滤。
- desktop：个人 Worker 深链激活、令牌加密、托盘与更新提示、backend Worker 模式；需与已有正式核对助手区分，不直接替换已发布安装包。
- 首页及样式草稿：不等同于 Vercel 已发布首页改动。

独立目录 `/Users/zt27532/.codex/worktrees/employee-export-fix/New project 2`：

- 旧版正式工浏览器导出：稀疏单元格、压缩、Web Worker、明确下载文件名，尚未提交；针对旧流程，不能与新版服务端活动导出整段同时覆盖。
- 国内外包存储错误提示与活动数量不可用状态：尚未提交；公司需验证 OBS 错误映射，不能只移植 Supabase 402 文案。

Vercel 整合目录还有正式工持久化适配未提交，已在本会话记录测试与批准配置；它不属于公司已发布功能。

## 已有功能及同步保护

逐文件/目录核对确认以下业务实现与 Vercel 已发布代码一致，不应再次列作缺失：海外薪资 18 个工具资源/vendor/service、FBU engines/parser/exporter/runs、招聘 calculator/rules/import validation、admin.js。海外工具 router/tasks 的差异主要是 OBS 适配和公司安全登录适配，不能反向覆盖。

公司 master 已包含 10 月 3 日安全整改、MySQL/OBS、FBU 快照压缩相关代码及公司上传模式。平台与公司整树有 139 个路径差异，其中大量是公司专有部署和安全文件；差异数量不代表 139 个待补功能。

## 建议顺序

1. 社保离职规则与并发恢复、东南 B2B 工龄奖、夜班配置：先补业务准确性与可靠性，并保留公司安全与存储。
2. 刷新保持位置、字体与首页：集成前端便利性。
3. 政策资讯：另落实 MySQL 迁移和公司定时采集。
4. 正式工新模块：单独完成公司 MySQL/OBS/任务适配与真实业务验收，不能将 Vercel 暂停状态当成公司可直接发布。

本次没有重新运行业务测试；结论来自已拉取提交、实际文件差异和只读健康探测，不代表候选集成后的测试或线上业务验收通过。
