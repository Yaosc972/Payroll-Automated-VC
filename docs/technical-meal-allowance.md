# 技术部餐补

入口 `/china-employee-payroll.html` 将餐补拆为集团技术部和 WX 技术部。集团选择月份、确认后直接读取北森考勤；WX 选择月份后导入外部系统日报。两种来源分别保存批次、查询结果和导出，不混合核算。默认上个月，沿用既有餐补规则与计算引擎。

## 数据与规则

集团沿用 `meal_allowance.py` 中的组织、工号、姓名排除、班次、工作日、含补签打卡及公出备注规则，20 元/补贴日。先读取核算月月报及关联主职任职，按月末组织层级确定候选人员；包括当月任职曾属于技术组织的转出人员，再根据日考勤 `AttendanceOrgId` 判断当天组织范围。日考勤的原始含补签打卡时间保留，不用月报天数代替日记录，也不把缺字段当成零。

| 原导入表字段 | 日考勤 API 字段/关联 |
| --- | --- |
| 工号、员工、人员状态 | `StaffId` / `UserId` → 月报关联任职及员工基本信息 |
| 二至五级组织 | `AttendanceOrgId` → 核算月末组织层级 |
| 考勤日期 | `SwipingCardDate` |
| 首打卡(含补签) | `FirstCardIncludeFillCheck` |
| 末打卡(含补签) | `LastCardIncludeFillCheck` |
| 当前班次 | `OIdWorkShift` → 班次接口 `Name` |
| 日期类型 | `DateType` → 租户 `Attendance.DateType` 选项中文名称 |
| 备注 | `RetroactiveRemark` |

北森接口沿用已有服务凭据，仅在后端调用：

- `/AttendanceOpen/api/v1/AttendanceStatistics/GetLateArrival`：批量查询日考勤，不修改或重算北森记录。
- `/AttendanceOpen/api/v1/WorkShift/GetWorkShiftInfo`：班次名称。
- `/dataservice/api/DataSource/GetDataSource`：动态日期类型枚举。
- 已有月报、员工任职、基本信息及 `GetSubOrganizations` 历史组织接口。

候选依赖所选月份已生成的北森月报。日考勤按最多 100 人分批，每页 100 条、最多 4 个并发。分页总量变化、不完整、月份错位、重复员工日期、无法解析的身份/组织/班次/日期类型会终止并展示原因，避免生成部分金额。WX 文件缺字段、重复工号日期、日期跨月或与选定月份不符时直接提示修正。

## 交互、批次与导出

三个科目共用活动列表，每个活动独立保存月份与核算结果，可回看和导出；详见 `china-payroll-activities.md`。工作台保留月份、核算状态、汇总和明细，删除旧双来源导入面板与规则配置长文。集团三个阶段为匹配人员、读取考勤、核对并生成结果，各有独立本地 GSAP 动画。日考勤阶段的百分比使用实际已读取数/总数；总量未知及最后阶段显示处理状态，不估算百分比。支持减少动态效果、后台暂停、错误重连与重复提交防护。

`POST /api/china-employee-payroll/meal-allowance/beisen/runs` 接收 `{"month":"2026-09"}`，返回 202 与批次 ID。`GET .../runs/{id}` 查询进度或结果。WX 沿用 `POST .../meal-allowance`，表单含 `source_type=wx`、`month`、`attendance_files`。历史接口和导出路径兼容旧批次。

新批次保存 `data-source.json`（用于计算的中文字段快照）、`result.json` 和 `metadata.json`。导出包含餐补结果及该批次考勤源数据，首行表头、整数天数无尾点、金额保留两位小数，文本不作为 Excel 公式。文件名含中文核算月份、来源科目和计算时间。历史旧导入批次继续保留原始源表。

本地单进程后台任务同一时间只运行一项集团餐补，重启中断明确显示失败。批次沿用系统临时目录 `sigma_workbench_china_employee_payroll_runs`，不是永久台账；密钥与 token 不写入文件或前端。

## 验证

定向测试：

```sh
python3 -m pytest tests/test_meal_beisen.py tests/test_meal_api_runs.py tests/test_china_employee_meal_allowance.py tests/test_relocation_allowance.py -q
```

真实 WX 2026 年 5 月日报：1,317 条，43 人，27 人有补贴，126 个补贴日，2,520 元；新导入与导出核对一致。

2026-10-09 权限开通后真实接口验证：集团 2026 年 9 月读取 3,314 份月报匹配候选，550 名技术部员工共 16,412 条日考勤；316 人有补贴，1,836 个补贴日，合计 36,720 元。接口的月报组织 ID 为字符串、日考勤组织 ID 为数值，关联前统一规范化。空打卡和备注字段会被北森省略，按空值处理；组织本身处于二/三级时没有更下级属于合法层级，不作为缺字段报错。

与既有 `考勤记录_20260920135212.xlsx` 对账：共同技术组织 608 行全部覆盖，班次、日期类型、二至五级组织一致。9 月 1—19 日共同 578 行，逐日金额均一致，共 440 元；9 月 20 日两条末打卡在旧表导出后更新到 21:00 以后，各增加 20 元，所以共同样本最新为 480 元。相同输入的金额差异为零。全量源数据重算逐日金额与结果一致。仅将无个人信息的汇总记入文档，真实源数据保存在本地批次目录。
