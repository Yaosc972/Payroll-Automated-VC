# 海外劳务 Supplier Profile 准入契约

外部 Supplier Profile 是运行配置，不因文件存在于 `data/supplier_profiles/` 就自动生效。Resolver 只启用同时满足以下条件的 Profile：

- `status` 必须为 `approved`。
- `version` 必须是正整数。
- `approvedBy` 必须记录审批人或审批主体。
- `approvedAt` 必须是带时区的 ISO 8601 时间，例如 `2026-07-15T09:30:00+08:00`。
- `deprecated` 不得为 `true`。

最小已批准配置示例：

```json
{
  "key": "supplier-family-v1",
  "aliases": ["supplier staffing"],
  "version": 1,
  "status": "approved",
  "approvedBy": "payroll-admin@example.com",
  "approvedAt": "2026-07-15T09:30:00+08:00"
}
```

缺少任一审批字段、时间不带时区、版本非法或状态为 `draft` 时，Loader 仍可读取该文件用于检查和治理，但 Resolver 必须跳过，回退到内置或默认 Profile。

自动抽取生成的 Profile 固定写为 `status=draft`。业务审批应在验证文档家族和 Golden 结果后显式补齐审批字段；不得只把文件复制到运行目录，或只把 `status` 改成 `approved`。

批次 metadata 中的 run-local Profile 候选遵守同一审批契约。候选显示为 `active`、完成一次 metadata 回放或由用户确认，都不能替代审批字段与 Golden；不满足契约时正式解析必须忽略它。

正式 UAT 还要求 Profile 位于发布包的 `data/supplier_profiles/`。`LABOR_SUPPLIER_PROFILES_PATH` 或 `SUPPLIER_PROFILES_OUTPUT_DIR` 指向项目外、软链接到项目外或指向不存在路径时，运行 build 必须标为 `unverified`，不得开始正式核对。
