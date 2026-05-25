# 招聘奖金与内推奖金核算平台

这是把 Excel 核算模板产品化的小平台版本。平台不依赖 AI 计算，后端使用确定性的 Python 规则引擎完成奖金计算。

## 功能

- 上传包含 `导入_月度数据` sheet 的 Excel 文件
- 每次上传生成独立核算批次，保留原始导入、初算结果、待确认表、最终结果和差异报告
- 自动读取平台内部规则库中的规则表
- 计算招聘奖金明细、招聘奖金汇总、内推奖金汇总
- 输出异常清单
- 支持下载待确认表、上传确认结果后生成最终汇总
- 支持上传线下核算表或复核表，生成平台与线下差异报告
- 导出计算结果 Excel

## 启动

在项目根目录执行：

```bash
python3 -m uvicorn bonus_platform.app:app --reload --port 8000
```

然后打开：

```text
http://127.0.0.1:8000
```

如果 8000 端口已被占用，可以换成：

```bash
python3 -m uvicorn bonus_platform.app:app --reload --port 8001
```

## 目录结构

```text
bonus_platform/
  app.py              # Web 入口和 API
  config.py           # 路径与系统配置
  engine/
    compare.py        # 平台与线下 Excel 差异报告
    calculator.py     # 奖金计算主流程
    models.py         # 数据结构
    runs.py           # 本地批次目录和元数据管理
    rules.py          # 规则读取和匹配
    workbook_io.py    # Excel 读取/导出
  static/
    index.html        # 页面
    styles.css        # 样式
    app.js            # 前端交互
```

## 推广使用原则

1. 保持 `导入_月度数据` 表头不变。
2. 平台主流程只按当前规则计算本月数据，不读取旧规则历史奖金表。
3. 规则变化时先维护平台规则库，再由平台读取新规则。
4. 每月上传 HR 系统导出文件后先生成初算批次，复核异常和待确认项。
5. 有待确认项时下载待确认表，薪酬组判断后上传确认结果，平台生成最终结果。
6. 如需验算，可上传线下核算表或复核表，平台生成招聘/内推汇总和明细差异报告。

## 批次化 API

- `POST /api/runs/calculate`：上传月度导入表，创建初算批次。
- `GET /api/runs`：查看历史批次。
- `GET /api/runs/{id}`：查看单个批次详情。
- `POST /api/runs/{id}/finalize`：上传待确认结果，生成最终结果。
- `POST /api/runs/{id}/compare`：上传线下表，生成差异报告。

## 当前状态

平台已从单次上传页升级为月度核算工作台，具备本月上传、当前规则计算、批次留痕、待确认、最终汇总、差异检验和结果归档能力。旧规则历史结转不进入主计算流程。
