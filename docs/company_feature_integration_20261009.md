# 公司功能集成交接 — 2026-10-09

状态：六组功能已选择性集成并在本地提交；本地验证完成。远端推送尚未完成：2026-10-10 公司 DNS 已恢复，但本机缺少可用的公司 Git 写入身份。尚未执行公司环境迁移、绑定新增密钥、部署预览或生产发布。Vercel 正式工发布仍暂停。

## 代码来源与范围

- 公司仓库：`gitlab`，`https://git.eminxing.com/zt27532/hras-global-payroll-workbench.git`。
- 集成基线：`gitlab/master = 0d1411ceb605eacbac83e6fcbea9d1cde2cd822e`。集成前及提交前均通过 `git ls-remote` 核实。
- 候选分支：`codex/company-feature-integration-20261009`。
- 隔离工作区：`/Users/zt27532/.codex/worktrees/company-feature-integration-20261009/New project 2`。
- 正式工来源：`cca1f001e963c53ace2c82eb5cee9aef13c5c495`。仅取该已提交功能，没有合并来源整条分支或携带其未提交草稿。
- 保留公司已有安全整改、登录、模块开放范围、OBS 适配、MySQL 接口和 Dockerfile。`auth.py`、`permission-guard.js`、底层 MySQL/OBS/公司活动文件接口、`vercel.json` 与基线无差异。

| 功能组 | 来源提交 | 公司集成提交 |
|---|---|---|
| 社保待离职、月初离职规则、并发历史恢复 | `bd49877d`, `644d12a3`, `aa30bb7c` | `9a220375`, `9f16f7cb`, `68cbaabf` |
| 东南 B2B 工龄奖 | `0f563336` | `470ce2a4` |
| 9 个夜班班次、缺失班次弹窗、跨月配置 | `2971abdc`, `9f4f0f6b`, `9efcc5be`, `9e904cc6` | `71b8be4b`, `b708a8a6`, `ecbf10e9`, `27682674` |
| 新首页、官方政策资讯、侧栏及窄屏适配 | `637a5e40`, `421355a1`, `460fff8b`, `a4fe0db2` | `4c4cdd24`, `75bb6283`, `41d3e6b6`, `aa21a498` |
| 刷新恢复、Windows HarmonyOS 字体 | `cb45d53c` | `a2c5238a` |
| 正式工三科目与独立活动 | `cca1f001` | `984fa6fd` |

公司适配提交：`cac048d2`；FBU 公司脚本缓存哈希修正：`75747cc7`。共享文件逐项保留公司代码，没有覆盖公司登录与上传流程。

未纳入：原工作区海外劳务识别、FBU 旧字段兼容、桌面个人 Worker、首页样式及旧版浏览器导出等未提交草稿。它们需要各自的提交和验证，不能自动带入本次候选。

## 公司适配

正式工新活动和任务使用 MySQL，输入、源快照、结果和导出使用现有私有 OBS 接口。请求只负责创建/入队/查询，持续运行的独立 Worker 负责长任务。创建请求及入队幂等；任务租约、心跳和 token 隔离阻止旧 Worker 覆盖新任务；最多三次接管，超限失败可重新核算。不会因为实例 `WORKER_ID` 不同误报失败。

查询、创建、核算、回看和导出继续要求现有正式工模块权限。创建人和头像来自服务端飞书会话，不接收客户端伪造身份。北森配置只读服务器环境变量，不读取 macOS Keychain。既有餐补历史从 OBS 恢复，旧 ID 保持可回看；新 ID 使用持久化队列。

政策资讯使用现有 MySQL adapter。公司常驻进程每小时轮转最多 8 个官方来源，MySQL 命名锁避免多副本重复采集；失败保留已有文章。调度默认关闭，由部署清单显式开启，未复制 Vercel Cron 配置。

## 具体待批准变更

1. 在公司对应环境 MySQL 新建以下四张表，均为幂等、向后兼容的新增结构：
   - `policy_articles`、`policy_source_checks`。
   - `sigma_china_payroll_activities`、`sigma_china_payroll_jobs`，活动/任务按既有存储环境隔离。
2. 将 API 迁移阶段命令设为 `python -m scripts.migrate_company_features`。它保留原 FBU 迁移，再迁移政策资讯及正式工表；没有运行时自动建表。
3. API 设置 `SIGMA_CHINA_PAYROLL_BACKEND=mysql`、`SIGMA_POLICY_REFRESH_ENABLED=true`。
4. AIDeploy 新增一个 `china-payroll-worker`，同一构建组件，`kind=worker`，`replicas=1`，命令 `python -m bonus_platform.engine.china_employee_payroll.worker`。没有公网路由或端口。后台使用 MySQL 和私有 OBS，不依赖 Supabase Storage。
5. Worker 复用现有 MySQL/OBS 密钥，并在平台安全配置绑定 `BEISEN_APP_KEY`、`BEISEN_APP_SECRET`。文件仅保存名字，没有密钥真值。

API 与 Worker 的数据库、私有 OBS bucket 和 `SIGMA_LABOR_STORAGE_ENV` 必须一致；环境值沿用既有历史文件命名空间，不擅自切换。OBS 签名直传的真实读写、CORS 和权限须在预览验收，尚未验证真实 bucket。

审批依据：项目 `AGENTS.md` 的 “Do not modify authentication, secrets, database schema, deployment config, payment logic, or production wiring without explicit approval.” 用户此前批准的 Supabase 两表及 Vercel 配置不等于本次公司 MySQL 四表和 AIDeploy Worker 的批准。上述清单已在候选文件中准备，尚未作用到公司环境。

## 验证证据

记录见 `.codex-artifacts/company-validation-20261009.txt`。

- 本模块指定五文件命令：**130 passed**。
- 正式工持久化、OBS adapter、无本地缓存旧历史：**18 passed**。存储底层读写被测试替身替代，不代表真实 OBS 已验收。
- 独立本地 MySQL 8.0.46：**4 passed**，覆盖迁移重跑、16 次并发入队、独立进程恢复、租约接管/旧 Worker 隔离、环境隔离、回滚释放锁、重试上限、政策 upsert/失败保留及跨副本锁。
- 全量 Python 首轮：**2527 passed, 17 skipped, 1 failed**，唯一失败为 FBU HTML 缓存哈希仍引用来源脚本。已在 `75747cc7` 修正，复跑相关静态与公司安全检查：**310 passed**。其余代码未因该修复改动，未声称重新运行了完整全量套件。
- Node 回归：**101 passed**；文件直传专项检查通过（超过 4.5 MB、上传失败禁止开始、导出完整性与中文文件名）。
- 所有静态 JS `node --check` 和 `git diff --check` 通过。
- AIDeploy 官方 devkit **0.2.23 / rules v3.0**：`aideploy check` 输出 “✓ 未发现问题”。公开 JSON Schema 校验通过。没有本地 Docker 引擎，镜像构建及准入仍由 AIDeploy 预览执行。

测试数据库为专门初始化的 loopback 临时 MySQL、新建 `sigma_features_test`，没有读取或写入公司 MySQL；测试服务和临时数据库已在收尾清理。

## 同一输入真实材料回放

汇总及输入/导出 SHA256 见 `.codex-artifacts/company-real-material-replay-20261009.json`。通过真实本地 MySQL 队列和 Worker，文件层为本地替身；没有实时请求北森或写公司 OBS。

| 科目 | 月份 | 输入范围 | 核算金额 |
|---|---|---|---:|
| 集团技术部餐补 | 2026-09 | 16,412 条、550 人，320 人应发、1,852 天 | 37,040 |
| WX 技术部餐补 | 2026-05 | 同一真实 Excel：1,317 条、43 人，27 人应发、126 天 | 2,520 |
| ABU 职场搬迁补贴 | 2026-08 | 已保存的 184 人样本及核算月历史组织，94 人应发 | 91,300 |

三科目逐行结果与同份输入基线一致，跨 Python 进程恢复、活动隔离、幂等开始、默认头像、双工作表及 Excel 金额核对通过。ABU 是给定的 184 人样本，不能视为完整月度北森接口覆盖。

集团金额对照公司 `0d1411ce` 的既有规则。来源提交旧规则为 36,720，保留公司规则后的 +320 由深圳正常班 +400、首打卡缺失 -80 构成，不是后来补考勤造成的差异。

## 页面验收与上线门槛

本地 ego-browser 实际操作记录见 `.codex-artifacts/company-ui-uat-20261009.json`：确认弹窗、创建、三个独立活动、核算、刷新恢复、回看、三科目导出下载，以及失效头像加载默认图均通过。使用模拟服务端身份、录制北森响应和本地文件 adapter；WX 及 ABU 使用同一真实材料，集团 UI 使用一个非 zt 合成员工并正确不发补贴。真实集团数据金额由上述 MySQL 回放覆盖。

公司 `/api/health` 可达，只证明服务响应。AIDeploy 公开工具页可访问，但应用列表显示“网络连接失败”；未取得当前运行的 release/source SHA 和镜像 digest。不得将远端 `master` 当作线上制品证据。

批准后按公司发布流程执行：

1. 核实既有 AIDeploy 应用、生产 release/source SHA 和镜像 digest，保存实际回滚版本；代码比较基线 `0d1411ce` 仅为候选回滚参照。
2. 使用候选分支构建预览，确认四表迁移、API/Worker 相同环境、私有 OBS 和北森服务端配置。用有权限的登录账号验证实时北森集团/ABU及 WX 直传，刷新/跨实例回看、源数据、导出金额与头像。
3. 预览业务验收通过后，按平台审批发布同一个已验收镜像。Ready/健康检查不能替代业务验收。
4. 生产有权限账号复核后再正常合并公司 `master`；禁止强推。发生问题按保存的实际发布镜像回滚，新增表保留，不删除活动及文件。

本次没有发布链接、线上业务验证或已核实的生产回滚版本。不存在 Vercel 部署或 main 同步动作。

## 远端交付状态

提交前远端 `master` 核实为 `0d1411ce`；最终 `git push gitlab HEAD:refs/heads/codex/company-feature-integration-20261009` 失败：`Could not resolve host: git.eminxing.com`。后续解析及只读查询复核确认 `git.eminxing.com` 与 `hras-aideploy.ztn.cn` 均返回 `gaierror`。没有切换目的仓库或修改系统 DNS；公司网络恢复后只推送候选分支，先核对远端 `master` 是否有新修复，不直接推生产分支。

### 2026-10-10 复核

公司 Git 与 AIDeploy 域名已恢复解析，生产健康接口及 AIDeploy 首页 HTTP 200。重新 fetch 确认公司 `master` 仍为 `0d1411ce`，候选分支尚不存在于远端。HTTPS 推送返回 `could not read Username ... Device not configured`；使用本机已信任 SSH 主机记录的只读核对返回 `Permission denied`，没有可用的写入身份。未写入凭据、改变系统 DNS、修改远端或执行公司环境迁移/发布。

当前阻塞转为公司 Git 写入认证；另仍待公司四表/Worker 配置批准及真实北森、私有 OBS/CORS、登录权限、镜像构建和回滚版本的预览验收。原本地测试结果可继续用于未改动的业务代码，健康接口 200 不代表这些业务已在线验证。
