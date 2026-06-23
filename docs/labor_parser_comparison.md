# 海外劳务发票免费解析器对比

这个对比入口用于评估免费解析器是否值得接入正式核对流程。它只读材料，不创建批次，不写规则，不改变当前核对结果。

## 使用方式

```bash
python3 -m bonus_platform.engine.labor.parser_compare \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output-dir outputs/labor_parser_compare/latest
```

输出文件：

- `parser_comparison_summary.json`：结构化对比结果
- `PARSER_COMPARISON_SUMMARY.md`：业务可读摘要

快速抽样：

```bash
python3 -m bonus_platform.engine.labor.parser_compare \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output-dir outputs/labor_parser_compare/sample_latest \
  --sample-size 8
```

抽样结果只用于快速判断方向，不能替代全量真实材料复测。

生成人工确认答案模板：

```bash
python3 -m bonus_platform.engine.labor.parser_compare \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --sample-size 8 \
  --write-expected-template outputs/labor_parser_compare/expected_results_template_sample.json
```

模板中先只填写 `invoice_total`。这个金额必须来自人工复核后的 PDF 发票总额，不能直接复制程序输出。

用人工确认答案做准确性对照：

```bash
python3 -m bonus_platform.engine.labor.parser_compare \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output-dir outputs/labor_parser_compare/accuracy_sample \
  --sample-size 8 \
  --expected-results outputs/labor_parser_compare/expected_results_template_sample.json
```

如果模板里还没有填写 `invoice_total`，报告只会显示“未载入人工确认答案”。填完总额后，报告会显示已确认总额命中/未命中的数量。

## 当前对比范围

第一版只判断解析器是否具备继续评估价值：

- 本机是否已安装
- 是否能从 PDF 读出文本
- 是否发现总金额或金额线索
- 是否发现员工姓名线索
- 是否发现工时线索

纳入对比的候选：

- LiteParse
- PyMuPDF4LLM
- Docling
- Marker
- pdfplumber
- Camelot

## 2026-06-20 当前真实材料结果

已在 `/Users/zt27532/Documents/报账核对工具` 下检查 66 个 PDF。当前本机已安装并跑通：

- `pdfplumber`
- `PyMuPDF4LLM`

初步结果：

| 解析器 | 可运行文件 | 读出金额 | 人工确认总额命中 | 读出员工姓名 | 读出工时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| pdfplumber | 66 | 46 | 未填写人工答案 | 46 | 26 |
| PyMuPDF4LLM | 66 | 43 | 未填写人工答案 | 46 | 23 |

当前建议：

- 先把 `pdfplumber` 作为第一候选继续复测，因为它在这批真实材料里读出金额线索最多。
- `PyMuPDF4LLM` 作为补充对照，适合验证 Markdown 化文本是否更利于后续字段理解。
- 暂不把任何解析器直接接入正式核对流程；下一步要先填写人工确认的发票总额，再看“人工确认总额命中”列，验证总额是否真的读准。
- LiteParse、Docling、Marker、Camelot 当前未安装，暂不影响正式核对。

## 判断原则

优先继续测试同时满足这些条件的解析器：

- 能稳定读出金额线索
- 能读出员工姓名线索
- 能读出工时线索
- 对多个供应商格式表现一致

未安装或暂时失败的解析器不会影响正式核对。只有真实材料复测稳定后，才考虑进入正式抽取链路。
