# 社保报盘云端运行架构

## 决策

社保报盘不依赖单台长期运行的电脑。生产请求可以由任意 Vercel Function 实例处理，实例重启、扩缩容或切换部署后，仍读取同一批次和同一份文件。

## 生产链路

1. 浏览器调用 Sigma Workbench 的社保接口。
2. 批次、人工修改、月度基线、同步快照、模板和导出文件写入私有 Vercel Blob 命名空间。
3. 北森取数通过带服务令牌的 HTTPS 远程连接器完成；Vercel 不读取 macOS Keychain，也不依赖本机 Node 目录。
4. Vercel Cron 每两小时调用一次受 `CRON_SECRET` 保护的同步入口：一次读取北森全量候选和完整合同主体目录，按主体生成全部批次、轻量索引和导出预校验。
5. 只有全部主体成功生成后，系统才原子切换 `latest` 成功版本指针；任一主体失败时继续保留上一成功版本。
6. 页面进入时只调用 `/api/social-insurance/bootstrap`，读取最近成功版本、主体目录和默认主体批次，不扫描历史批次，也不发起北森实时查询或完成度轮询。
7. 人工修改和导出结果立即持久化；主体切换按发布版本内的固定 `runId` 读取，避免命中尚未完整发布的新批次。

## 生产必需配置

- `SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND=blob`
- `SIGMA_SOCIAL_INSURANCE_STORAGE_ENV=production`
- `BLOB_READ_WRITE_TOKEN`
- `SIGMA_SOCIAL_INSURANCE_CONNECTOR_URL`
- `SIGMA_SOCIAL_INSURANCE_CONNECTOR_TOKEN`
- `CRON_SECRET`
- 现有登录、社保模块权限和审计配置

云端缺少持久化存储时，接口必须拒绝写入 `/tmp`，不得返回虚假的成功结果。

发布清单只保存主体名称、候选人数、批次 ID、汇总和预校验，不保存员工姓名、证件号码等个人信息。员工明细仍按当前所选主体从私有批次对象读取，不会把全部主体名单一次性下载到浏览器。

## 连接器约定

连接器只接受 HTTPS 和 Bearer Token：

- `POST /subjects`：接收周期和规则版本，返回 `subjects` 聚合列表，不返回员工明细。
- `POST /sync`：接收周期、确认日、主体和规则版本，返回标准化 `records` 与脱敏 `sourceSummary`。

北森原始响应不得进入日志、批次 JSON 或浏览器响应。连接器负责保存北森应用凭据、执行限流重试，并返回已验证规则引擎的标准结果。

## 本地模式

本地目录、macOS Keychain、Node 引擎和 APScheduler 只用于开发及回归测试。设置 `VERCEL` 后，这些能力不能成为生产兜底。
