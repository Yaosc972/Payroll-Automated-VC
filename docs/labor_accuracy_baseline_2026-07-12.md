# 海外劳务核对能力基线（2026-07-12）

## 结论

- 当前可支持受控内部 UAT，但不能宣称对未知供应商全面准确。
- 文本型发票已有较强结构化核对能力；图片型发票仍是主要上线缺口。
- 未经业务审核的历史批次只计覆盖率，不计准确率。

## 材料覆盖

- 原始材料组：20
- 文件：149，唯一哈希：149，重复副本：0
- PDF：121，文本结构型：84，文本稀疏：5，无文本层/图片型：32

| 材料组 | PDF | Excel | PDF 类型 | 真值状态 |
| --- | ---: | ---: | --- | --- |
| 29仓 | 2 | 1 | image_or_empty:1，text_structured:1 | 待业务审核，仅覆盖 |
| 5.25-5.31已报账 | 4 | 0 | text_structured:4 | 待业务审核，仅覆盖 |
| DCGCB | 1 | 1 | text_structured:1 | 待业务审核，仅覆盖 |
| DCGCB2 | 1 | 2 | text_structured:1 | 待业务审核，仅覆盖 |
| Grande- | 1 | 2 | text_structured:1 | 待业务审核，仅覆盖 |
| KW25 Armz GmbH | 12 | 2 | text_structured:12 | 工程复核样本 |
| SSS 5.11-5.17 | 4 | 6 | text_structured:4 | 待业务审核，仅覆盖 |
| Tru Staffing（反面教材） | 7 | 2 | sparse_text:3，text_structured:4 | 待业务审核，仅覆盖 |
| fairway已报账 | 6 | 1 | text_structured:6 | 待业务审核，仅覆盖 |
| fairway已报账2 | 6 | 1 | text_structured:6 | 待业务审核，仅覆盖 |
| fairway已报账3 | 6 | 1 | text_structured:6 | 待业务审核，仅覆盖 |
| osi | 5 | 1 | sparse_text:1，text_structured:4 | 待业务审核，仅覆盖 |
| osi 2 | 5 | 1 | text_structured:5 | 待业务审核，仅覆盖 |
| osi3 | 5 | 1 | sparse_text:1，text_structured:4 | 待业务审核，仅覆盖 |
| oss | 7 | 1 | image_or_empty:7 | 待业务审核，仅覆盖 |
| oss 2 | 8 | 1 | text_structured:8 | 待业务审核，仅覆盖 |
| oss3 | 7 | 1 | text_structured:7 | 待业务审核，仅覆盖 |
| prompt | 12 | 1 | image_or_empty:12 | 待业务审核，仅覆盖 |
| prompt缺2仓和9仓未报账 | 12 | 1 | image_or_empty:12 | 工程复核样本 |
| workforce已报账 | 10 | 1 | text_structured:10 | 待业务审核，仅覆盖 |

## 已复核回归

### Armz KW25 德文文本发票：通过

- PDF/Excel/差额：248930.05 / 248491.82 / 438.23
- 明细覆盖率：1.0
- 批次门禁：ok；状态：已生成差异报告
- 证据等级：独立金额闭合与员工/仓库结构复核，尚未业务签字

### Prompt 缺报账仓库图片发票：通过

- PDF/Excel/差额：92549.15 / 104780.55 / -12231.4
- 明细覆盖率：0.17
- 批次门禁：ok；状态：已生成差异报告
- 证据等级：整批总额与仓库差异人工复核；员工明细仅部分覆盖

## 上线门槛判断

1. 文本型未知供应商：允许 UAT，但必须满足金额闭合、币种一致、仓库归属唯一和差异留痕。
2. 图片型未知供应商：当前只允许人工复核流程，不允许系统自动放行。
3. 发布口径：准确率只统计业务确认或独立人工复算样本；其余材料只统计解析覆盖率。
4. 下一优先级：提升图片型发票员工明细覆盖，并让前端明确显示整批明细覆盖率。
