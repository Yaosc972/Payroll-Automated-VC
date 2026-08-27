# 社保报盘北森连接器

该目录部署为独立的 Vercel 服务，只暴露：

- `POST /subjects`
- `POST /sync`
- `GET /health`

所有业务接口都要求 `Authorization: Bearer <CONNECTOR_TOKEN>`。北森原始响应只在函数内存中处理，不写文件、不写日志，也不会包含在响应中。

## 必需环境变量

- `CONNECTOR_TOKEN`
- `BEISEN_APP_KEY`
- `BEISEN_APP_SECRET`
- `SOCIAL_INSURANCE_RULE_VERSION=2026.08.27-07`

可选：`BEISEN_BASE_URL`，默认使用北森开放平台 HTTPS 地址。

连接器每次同步都会从北森实时任职记录取得离职状态、最后工作日、停保属性和变更时间，并把最小离职判断上下文返回给 Workbench Cron 持久化。任职记录变更时间不冒充审批创建时间；缺少可靠审批时点或停保属性时强制人工确认。正常 Preview 和 Production 部署都不需要业务人员按月上传离职文件。

## 兼容变量

- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64`
- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE`

这两个变量只用于旧部署迁移期间补充北森实时记录未返回的离职上下文，不再是健康检查或同步的必需配置。若继续配置，必须同时提供快照内容和有效的 `YYYY-MM-DD` 快照日期；缺少日期或内容不可读取时会整份忽略并转用北森实时任职记录。快照不得提交到 Git，只能包含规则需要的最小字段并保存为 Vercel Sensitive 环境变量。

`lib/rules.mjs` 的 SHA-256 为 `c63c60bca499c4bb2468b97dc60e3dfb69b461bf10a59bbade0107cdb116d2a3`，发布验收后应以该值核对部署代码。`lib/admin-dictionary.json` 由深圳政务模板的“行政区划字典”工作表生成，不包含员工数据。
