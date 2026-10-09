# 中国区正式工核算活动

三个科目共用 `china-employee-payroll.html#activities`：集团技术部餐补、WX 技术部餐补、ABU 职场搬迁补贴。列表支持名称搜索、科目/月度/状态筛选以及每页 20 条的分页。已有核算批次自动纳入列表，原来的结果和导出仍可打开。

列表展示创建人的姓名和头像，也可以按创建人姓名搜索。新活动在服务端从现有登录会话保存创建人 ID、姓名及头像地址，复用飞书登录已保存的 `avatarUrl`；客户端不能指定创建人。未登录的本地活动显示“本地用户”。旧记录缺少创建人时显示“未记录”，不补写当前查看人。头像地址缺失、无效或图片加载失败均使用用户提供的 `assets/payroll-default-avatar.png`。此功能不更改登录流程或用户数据库。

从薪酬科目页选择科目、月份并填写可选活动名称。同月可以建立多个独立活动；默认名称为月份和科目。北森科目确认后创建活动并自动开始；WX 创建待核算活动后上传该月份的 Excel。

每个活动使用独立 UUID，链接为 `?activity=<UUID>#<subject>`。刷新或重新打开只读取该活动；核算中的活动继续连接已接受的后台任务，不会重新提交。已核算活动保留原结果；复算应新建活动。失败可以在原活动内重试，保留历史任务关联。

## 接口和存储

- `POST /api/china-employee-payroll/activities`：创建活动。参数 `subject`、`month`、可选 `name`，可选 UUID hex `requestId` 用于创建请求去重。
- `GET /api/china-employee-payroll/activities`：按 `search`、`subject`、`month`、`status`、`page`、`page_size` 查询。
- `GET /api/china-employee-payroll/activities/{id}`：读取状态、任务关联和汇总。
- `POST /api/china-employee-payroll/activities/{id}/start`：根据活动保存的科目和月份开始。WX 使用 multipart `attendance_files`；集团餐补和搬迁补贴无需上传。

活动元数据存放于既有餐补运行目录的 `activities/`，使用原子 JSON 写入，不更改数据库。考勤、计算结果和 Excel 继续使用原来的任务存储和导出接口。列表不会返回员工明细或原始考勤。未关联活动的旧任务通过确定性 UUID 提供稳定链接，不改写旧结果。服务重启中断的任务会显示失败，可在活动内重试。

## 验证

后端验证覆盖三个科目汇总、同月结果隔离、创建/开始去重、运行中重连、并发 WX 上传、失败重试、旧记录分页、重启与缺失文件。浏览器验证列表筛选、独立结果打开/刷新、新建 WX 活动后刷新继续上传，以及集团/搬迁/WX 的历史结果和导出。
