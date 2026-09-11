# 社保完整更新生产发布记录（2026-09-11）

## 基线与集成

- 实际生产发布线：`codex/domestic-production-20260909`，工作区 `/Users/zt27532/Documents/sigma-domestic-production-20260909`。
- 发布前实际工作台版本：`63ac5eca4c33e746d1afcf3e5e91cba86c6f9f26`，部署 `dpl_ALqnK1nceqrdDscTHvbz5czQzU6d`。
- 源提交：`dc7bea36e3c7aa3bf02fd34a989eb0c7edf8fd92`，以前序 `93d53a24` 为基线；选择性 cherry-pick 为 `bfff48b1`，没有覆盖其他模块。
- 原工作区两处定时补丁保存为 stash `preserve pre-existing social cron patches before dc7bea36 integration`；集成后文件与该补丁完全一致，无需重复应用。
- 工作台规则包与生产连接器统一使用 `2026.09.10-01`；两端原显式环境版本均为 `2026.08.27-07`，发布时必须同步更新。
- 每天北京时间 08:00：`/api/social-insurance/cron/refresh`，UTC `0 0 * * *`。代码配置不代替 Vercel 实际登记验收。

## 发布前数据状态

- 成功名单版本 `release_20260903082821_0c464589`，发布时间 `2026-09-03T08:28:21.912807Z`。
- 33 个主体、175 人；32 个草稿批次、1 个已确认批次。已记录各历史批次的摘要与内容哈希用于上线后比对，不在仓库保存人员数据。
- 周期 `2026-07-16` 至 `2026-08-15`，确认日 `2026-08-16`；这是 9 月 11 日最近完整结束的周期。
- 默认主体缺少有效政务模板，不能用审核清单或自造空表替代真实报盘验收。

## 回滚点

- Git 标签：`rollback/social-insurance-20260911-63ac5eca`。
- 旧工作台：`https://sigma-workbench-7aykr6xee-yaosc-s-project.vercel.app`。
- 旧生产连接器：`https://sigma-social-insurance-connector-7b5oxl55a-yaosc-s-project.vercel.app`，部署 `dpl_23tLJttiZ6EPS7tBXFpYzxWUvVyY`，提交 `f68000959b65e56ed876ff3315d5914374151148`。
- 旧工作台连接器地址配置：`https://sigma-social-insurance-connector.vercel.app`。
- 配套恢复两端旧部署及原环境配置；不得只回滚一端造成规则版本不匹配。密钥保持不变。
- 部署回滚不回写名单、人工确认和模板，也不自动回退成功名单指针；数据问题需要另行核对具体发布版本，禁止覆盖历史人工确认。

## 验收边界

- 授权仅额外执行一次生产同步；若返回不确定，先查成功发布指针和日志，不盲目重试。
- 全部主体导出仅为审核清单，政府系统最终提交保持禁用。
- 最终部署 ID、同步结果和未解决事项以发布后的验收补记为准。
