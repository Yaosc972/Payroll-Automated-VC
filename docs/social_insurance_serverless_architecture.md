# 社保报盘云端运行架构

## 决策

社保报盘不依赖单台长期运行的电脑。生产请求可以由任意 Vercel Function 实例处理，实例重启、扩缩容或切换部署后，仍读取同一批次和同一份文件。

## 生产链路

1. 浏览器调用 Sigma Workbench 的社保接口。
2. 批次、人工修改、月度基线、同步快照、模板和导出文件写入私有 Vercel Blob 命名空间。
3. 北森取数通过带服务令牌的 HTTPS 远程连接器完成；Vercel 不读取 macOS Keychain，也不依赖本机 Node 目录。
4. Vercel Cron 每两小时调用一次受 `CRON_SECRET` 保护的同步入口，刷新最近完整周期的全主体快照。
5. 页面生成批次时优先使用持久化快照；人工修改和导出结果立即持久化。

## 生产必需配置

- `SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND=blob`
- `SIGMA_SOCIAL_INSURANCE_STORAGE_ENV=production`
- `BLOB_READ_WRITE_TOKEN`
- `SIGMA_SOCIAL_INSURANCE_CONNECTOR_URL`
- `SIGMA_SOCIAL_INSURANCE_CONNECTOR_TOKEN`
- `CRON_SECRET`
- 现有登录、社保模块权限和审计配置

云端缺少持久化存储时，接口必须拒绝写入 `/tmp`，不得返回虚假的成功结果。

## 连接器约定

连接器只接受 HTTPS 和 Bearer Token：

- `POST /subjects`：接收周期和规则版本，返回 `subjects` 聚合列表，不返回员工明细。
- `POST /sync`：接收周期、确认日、主体和规则版本，返回标准化 `records` 与脱敏 `sourceSummary`。

北森原始响应不得进入日志、批次 JSON 或浏览器响应。连接器负责保存北森应用凭据、执行限流重试，并返回已验证规则引擎的标准结果。

## 本地模式

本地目录、macOS Keychain、Node 引擎和 APScheduler 只用于开发及回归测试。设置 `VERCEL` 后，这些能力不能成为生产兜底。
