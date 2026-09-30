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
- `SOCIAL_INSURANCE_RULE_VERSION=2026.09.30-01`

可选：`BEISEN_BASE_URL`，默认使用北森开放平台 HTTPS 地址。

连接器每次同步都会从北森实时任职记录取得离职状态、最后工作日、停保属性和变更时间，并把最小离职判断上下文返回给 Workbench Cron 持久化。任职记录变更时间不冒充审批创建时间；缺少可靠审批时点或停保属性时强制人工确认。正常 Preview 和 Production 部署都不需要业务人员按月上传离职文件。

2026-09-30 修复：对本次候选 UserID 额外调用 `Employee/GetServiceInfoByIds`，显式使用 `option: "None"`，approvalStatus 列出全部枚举（Draft、Approving、Success、Refused、Effective、Invalid、Rejected、Temporary），每批最多 300 人，读取业务类型为 5（离职）的记录。不能用仅返回生效任职的员工时间窗查询代替此步骤；数字 option 0 加空状态列表的组合在真实验证中漏掉审批中记录，不再使用。草稿、撤回、作废、不通过的已翻译状态不参与判断；无法识别的状态保守转人工确认。查询失败或返回格式异常必须让同步失败，不降级为空离职记录；人员标识有效但业务类型为空的记录仅让对应人员转人工确认。

任职记录的 `CreatedTime` 也不是可靠的原申请时间：9 月 17 日案例现存离职任职记录是在当晚创建。当前新查询取得的离职记录标记 `processTimeReliable: false`。同一自然月入职且1～14日离职、最后工作日不晚于确认日的记录可独立判断：明确自愿停保自动排除，非自愿停保继续购买；缺失属性、冲突或15/16日边界交人工。其他依赖申请时间的情况仍交人工确认。BP 指定购买沿用工作台人工纳入，不假定上游存在该字段。旧任职最后工作日早于本次入职日的记录不阻挡重新入职。工作台与连接器规则版本须一起升级到 `2026.09.30-01`。

接口契约：[北森当前官方文档](https://open.italent.cn/?_qrt=html#/open-document?id=e0b9ab6d-0ca7-41cc-8104-6637961aee8d&menu=document-center)。另一个 `GetListByBussinessType` 接口在当前授权下返回 401，未采用、未扩大权限。新查询已通过真实只读请求，取得两条审批中离职记录；本地工作台均转待确认，确认/报盘被阻止，跨确认日期重算后仍保留待确认。尚未发布生产。

## 兼容变量

- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64`
- `SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE`

这两个变量只用于旧部署迁移期间补充北森实时记录未返回的离职上下文，不再是健康检查或同步的必需配置。若继续配置，必须同时提供快照内容和有效的 `YYYY-MM-DD` 快照日期；缺少日期或内容不可读取时会整份忽略并转用北森实时任职记录。快照不得提交到 Git，只能包含规则需要的最小字段并保存为 Vercel Sensitive 环境变量。

`lib/rules.mjs` 的 SHA-256 为 `855a901b9dabe11cf7c112fb28b4be5c98b18733afac153276e1db2f53779b7b`，对应规则版本 `2026.09.10-01`，发布验收后应以该值核对部署代码。`lib/admin-dictionary.json` 由深圳政务模板的“行政区划字典”工作表生成，不包含员工数据。
