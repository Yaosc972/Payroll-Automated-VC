# 数据准备与结果解释

不把原表原样交给计算脚本。AI先读取数据、保存字段映射和来源，再按契约输出 JSON；契约列出了规范字段名，原始列名可不同。模板 assets/input-template.json 故意保留缺失状态，不能直接用于发薪。

顶层：month（YYYYMM），employees（月考勤对象数组），sources（来源与覆盖范围）。科目按契约另需 daily、housing、abandonment_roster、seniority_roster、temperatures 或 night_config；不需要的可省略。

sources 每个数据源使用：
```json
{"employees":{"month":"202609","status":"provided","complete":true,"evidence":"月考勤.xlsx/Sheet1/第3—32行；已核对覆盖本次全部人员与整月，字段映射另附"}}
```
这只是结构示例，不能照抄证据。名单确认为空时使用空数组，status=confirmed_empty，evidence写明确认依据。日考勤覆盖声明不能代替遗漏行检查；与主表逐人核对排班、出勤总数和期间。全勤奖需要覆盖整月的逐日工作状态，包括非工作日，不能用自然周末推断排班。

工号必须为文本；数值须为有限非负数，源表真实零值才可写0。日期使用YYYY-MM-DD；入职日期必需时不可空；最后工作日字段必须存在，在职且无最后工作日时可填null。日考勤缺卡仅在原表确实缺卡时使用null，缺字段必须提醒。异常原因无异常时允许空字符串。上/下班时间使用00:00至23:59的HH:MM，跨午夜保留真实上下班钟点；不要自行对跨日数据取模。

住宿每行：工号、姓名、入住时间、退宿时间（尚在住=null）。纳入跨月仍有效住宿记录。自离/揽收工龄奖名单每行：工号、姓名，仅本批次生效，不跨月自动沿用。

高温登记每行：班次日期、测温班次（白班/夜班）、测温网点、测温温度。日考勤测温班次必须由真实排班时间确定；不得用当天最高温替代网点和班次匹配。无测温记录不能视为未达到阈值。

夜班 night_config 使用 shift_breaks 数组，每行 shift_code、effective_start_date、break_periods（如["23:00-24:00"]）。无休息时须有明确业务依据才使用空数组。不得将随包历史基线当作当月已确认配置。晋江额外排除名单在 jinjiang_exclusions，每行 employee_id、employee_name、reason、start_date、end_date；确认后 jinjiang_list_confirmed=true，没有名单也要确认。当前程序没有多版本同班次时段自动拆分，发生月中调整应先按有效期间拆分并审核合并。

线下结果 offline 数组每行：工号、姓名、考勤月份、科目（中文全称）、金额。必须记录对应 sources.offline；金额零须显式提供，不把空白看成零。程序不自动合并重复行，多条发放/冲正需先确认合并口径。只提供工资结果无原始核算数据时，可以做完整性检查，但不能宣称金额正确。

输出状态：blocked=未核算，calculated=核算完成，needs_review=存在暂算或未完成，verified=逐人核验通过，differences_or_unverifiable=存在差异或无法核验。results 中 amount=null 不能用于最终发薪，provisional_amount仅供复核。保留details和warnings，不删除未确认口径。

高温补贴另需 temperature_exclusions 数组，每行工号、姓名、工作地区、不享有原因、生效日期、结束日期；空结束日期使用null。空名单需在sources.temperature_exclusions明确confirmed_empty并保留来源证据；禁止省略名单后推定没有不享有人员。适用日期含首尾当天。不享有原因仅为办公地点有空调、固定排除名单、岗位不在晋江适用范围，且必须符合员工已确认资格。

测温网点可以自行填写；日考勤与测温登记名称一致时直接匹配。名称不一致时，在temperature_site_mapping使用原名称到目标名称的明确对照；不得由AI模糊猜测网点。缺少对应日期、网点或班次测温时只提供待复核结果。出库发运组过渡性高温补贴继续线下单独核算。

validate仅检查输入完整性与补充资料，不执行核算；validated不能解读为工资金额已经验证。每次输出附科目规则版本，包版本及源码指纹见references/provenance.json。
