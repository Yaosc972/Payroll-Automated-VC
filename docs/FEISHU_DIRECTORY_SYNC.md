# 飞书组织通讯录同步

后台管理可从飞书同步 `HRAS 人力综合条线` 根部门及其子部门成员。同步只负责身份与组织信息，不自动授予任何业务角色。

## 生产环境变量

- `SIGMA_FEISHU_DIRECTORY_SYNC_ENABLED=1`
- `SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID`：HRAS 人力综合条线的飞书 department_id
- `SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_NAME=HRAS 人力综合条线`（可选，仅用于展示和根部门名称兜底）
- 复用平台 Production 已有的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`

真实同步同时要求 `VERCEL_ENV=production`。Local 和 Preview 即使误配启用变量，接口也会拒绝执行，并且不会请求飞书通讯录。

## 飞书应用权限与数据范围

应用需要具备以下通讯录只读权限：

- 部门基础信息只读
- 用户基础信息只读
- 用户所属部门只读
- 用户 user_id / employee_id 只读
- 员工工号只读
- 企业邮箱只读（用于兼容归并已有账号）

飞书应用的通讯录数据范围应限制为 `HRAS 人力综合条线` 及其子部门。服务端仍会以 `SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID` 再做一次范围限制。

## 身份与权限规则

- `feishu_user_id` 是用户的唯一业务标识；数据库内部 `admin_users.id` 继续作为稳定外键，避免破坏历史权限、会话和审计记录。
- 已有用户按 `feishu_user_id`、`open_id`、`union_id`、企业邮箱依次归并，不重复建人。
- 组织范围外用户仍可通过飞书登录，显示为“组织外已登录”，不会被组织同步删除或停用。
- 同步不会修改 `admin_user_roles`，所有模块角色继续由系统管理员显式授权。
- 页面不展示入职日期、直属主管、岗位、员工类型和工作地点。

## 发布前检查

1. 确认 Production 的根部门 ID 与应用数据范围一致。
2. 先调用后台状态接口确认 `directory.canSync=true`，不得输出任何密钥。
3. 由系统管理员在后台手动执行一次同步，核对部门数、人员数和归并结果。
4. 抽查范围外已登录用户仍存在且权限未变。
5. 检查审计日志中的 `sync_feishu_directory` 记录。
