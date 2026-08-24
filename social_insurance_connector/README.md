# 社保报盘 UAT 北森连接器

该目录部署为独立的 Vercel Preview 服务，只暴露：

- `POST /subjects`
- `POST /sync`
- `GET /health`

所有业务接口都要求 `Authorization: Bearer <CONNECTOR_TOKEN>`。北森原始响应只在函数内存中处理，不写文件、不写日志，也不会包含在响应中。

## Preview 环境变量

- `CONNECTOR_TOKEN`
- `BEISEN_APP_KEY`
- `BEISEN_APP_SECRET`
- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64`
- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE`
- `SOCIAL_INSURANCE_RULE_VERSION=2026.08.24-06`

可选：`BEISEN_BASE_URL`，默认使用北森开放平台 HTTPS 地址。

`lib/rules.mjs` 来自已验证的 UAT 规则引擎，SHA-256 为 `88710b4061620d48ea5eab70366f4d1d4ca3c465e065789e4e84c5a8ee4e0cf4`。`lib/admin-dictionary.json` 由深圳政务模板的“行政区划字典”工作表生成，不包含员工数据。

离职快照不得提交到 Git。部署时只提取规则需要的 6 个字段，使用 gzip + base64 编码后保存为 Vercel Sensitive 环境变量。
