# 离职申请日期展示

开发工作树：`New project 2-social-insurance-feedback`。本次仅改本地，未部署。

## 日期来源

北森源数据视图优先展示当前任职的 `lastWorkDate`。为空时，从连接器保留的
`source.departureRecords` 中查找审批中的离职任职记录，展示最后工作日并标注
“离职申请中”。标签提示来源为审批中的离职任职记录、尚未生效。

- 不覆盖当前任职的原始日期，不将申请中日期解释为已离职。
- 作废、撤回等记录沿用连接器已有过滤；前端只接受明确的审批中状态。
- 早于本次入职的旧离职记录不作为日期补充。
- 多个不同的审批中日期显示“日期待核对 / 申请日期冲突”，不任取一条。
- 此变更不改变是否购买的判断，也不取消待人工确认事项。
- 旧批次不会自动重写；本次仅给用户正在查看的本地易可达批次补充了实时核验的展示元数据，保留原审核决定。后续新同步会自动保存该字段。

## 发起时间调查

实时只读查询确认：目标员工有一条审批中和一条作废的离职任职记录；能取到
`workFlowProcessId` 和任职记录的 `createdTime`。后者尚未验证为原流程发起时间，
不得直接用于名单确认时点判断。

北森官方文档已确认以下查询的响应包含 `processStartTime`：

`POST /approvalcentre/api/v1/task/SearchByProcessDefCodeAndActivityDefCode`

该接口必填 `appName`、`processDefinitionCode`、`activityDefinitionCode`、
`taskCreatedTimeFrom`、`taskCreatedTimeTo`，任务时间跨度最大一个月。当前项目缺少
实际离职流程及节点编码，尚未调用，也未验证权限与目标流程的精确匹配。
不能只凭响应的任务审批人 ID 匹配离职员工。

[北森官方接口文档](https://open.italent.cn/?_qrt=html#/open-document?id=edbc7217-3d43-467e-bc11-92a3d8f214f2&menu=document-center)

此前 CLI 当前账号待办及默认近 30 天已办中没有匹配记录；该结果不代表所有流程中不存在。

### 后续只读验证：无需节点编码的查询已成功

官方 `GET /approvalcentre/api/v1/record/search` 接受 `approvalObjectId`，
返回完整审批操作记录，支持通过 `offsetId` 分页。将目标审批中任职记录的
`workFlowProcessId` 传入后，现有凭据调用成功（HTTP 200、业务 code 200），
返回 13 条操作记录且 `isLastData=true`。其中“开始”节点的“提交。”操作时间为
`2026-10-09T17:27:06.4670000`，可作为该实例实际提交时间的证据。
初次验证时未修改批次判断；后续接入情况见下节。
用户提供的候选流程定义编码不再是此查询的必要参数，也未在此次查询中验证。

[按审批对象查询操作记录的官方文档](https://open.italent.cn/?_qrt=html#/open-document?id=3e1d3be2-faad-467e-b51c-95d135fc913a&menu=document-center)

### 自动同步接入

连接器现对审批中、审批通过及生效的离职记录，按有效 `workFlowProcessId`
查询操作记录。同次同步按流程 ID 去重，顺序查询并读取全部分页，不自动重试。
只有恰好一条“开始 / 提交。”且时间格式有效时，才标记 `processTimeReliable=true`。
无时区时间按北森该租户的北京时间补 `+08:00`，避免 Mac/Windows 的本地时区差异。
缺失、多次提交仍待人工确认；接口失败、循环游标或分页超限直接停止同步。
作废记录不查询提交时间；任职记录创建时间仍不能作为替代值。

时间保存在 `confirmationRuleContext`，沿用现有确认日判断及快照重算逻辑。
实时查询已验证目标记录得到提交时间，并按 2026-09-16 确认日返回“增员 / 离职流程晚于名单确认时点”。
新增测试覆盖分页、缺失及多次提交、查询失败、不重试、同流程去重、作废记录跳过和确认上下文保留。

本地服务已重启并完成该周期的强制实时同步（29 个主体），易可达新批次
`sir_20261012142054_eb16dc26` 为 18 人、18 人规则可报盘、0 人待确认；
目标记录 `status=ready`、`decision=include`、无校验问题，仍未人工确认。
浏览器刷新后已显示 14:20 的最新集成结果。未执行政务上传或申报。
连接器 44 项测试通过后，新增同流程去重测试所在文件 20 项通过；Python MVP 81 项通过。

## 验证

- Python 社保 MVP 测试 81 项通过。
- Node 连接器测试文件 18 项通过。
- JavaScript 语法检查与 `git diff --check` 通过。
- Ego 浏览器实测：易可达批次、北森源数据视图显示 `2026-10-13` 和“离职申请中”，标签来源说明正确。
