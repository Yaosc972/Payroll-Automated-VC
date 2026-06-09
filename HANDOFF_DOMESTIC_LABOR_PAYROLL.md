# 国内劳务工薪酬核算模块 · 交接文档

> 最后更新：2026-06-08
> 负责人交接：Claude → 下一位工程师

---

## 1. 模块完成度总览

### ✅ 已完成

| 子模块 | 状态 | 说明 |
|--------|------|------|
| 计算引擎 | ✅ 100% | 4个引擎（全勤奖、餐补、外宿补贴、工龄奖）均已实现 |
| 文件解析器 | ✅ 100% | 支持 .xlsx/.xlsm/.xls，支持密码解密 |
| 模板生成器 | ✅ 100% | 4个引擎模板，含表头、说明行、示例数据 |
| Excel导出器 | ✅ 100% | 计算详情 + 汇总统计 + 异常记录 三个Sheet |
| 文件存储层 | ✅ 100% | 每个任务一个目录，metadata.json + 上传文件 |
| API路由 | ✅ 100% | 10个端点，含后台计算、轮询、导出、下载 |
| 前端页面 | ✅ 100% | domestic-labor.html + domestic-labor.js，4步向导 |
| 样式系统 | ✅ 100% | 引擎卡片、KPI 6列、任务状态卡等 |
| 首页入口 | ✅ 100% | 模块02已上线，labor.html 跳转到 domestic-labor.html |
| 单元测试 | ✅ 100% | 12个API测试用例 + 15个静态资源测试 |

### ⏳ 半成品 / 需要验证

| 子模块 | 状态 | 说明 |
|--------|------|------|
| 餐补引擎 | ⚠️ 部分 | 依赖日考勤数据的「正班时数」「刷卡加班」「是否异常」字段；模板测试数据中这些字段缺失，导致返回0 |
| 外宿补贴引擎 | ⚠️ 部分 | 依赖「外宿补贴标准」字段值为"150"（不是"/"），且需要日考勤数据验证出勤 |
| 工龄奖引擎 | ⚠️ 部分 | 依赖「二级部门名称」「岗位名称」「排班天数」等字段；测试数据格式不完整 |
| HRBP过滤 | ⚠️ 未验证 | 工龄奖揽收部需要HRBP名单，前端已支持传入，但未用真实数据测试 |

### ❌ 未开始

| 子模块 | 说明 |
|--------|------|
| 扣款计算 | 未实现独立扣款引擎（当前扣款逻辑分散在各引擎的排除条件中） |
| 补发计算 | 未实现补发引擎 |
| 历史版本比对 | 未实现跨月对比功能 |
| 数据校验层 | 未实现上传文件的格式校验（如列名检查、数据类型检查） |
| 批量任务管理 | 未实现批量删除、批量导出 |

---

## 2. 相关文件清单

### 前端文件

```
bonus_platform/static/
├── domestic-labor.html      # 算薪工作台页面（主入口）
├── domestic-labor.js        # 页面交互逻辑
├── labor.html               # 跳转页面 → domestic-labor.html
├── index.html               # 首页，模块02入口已更新
└── styles.css               # 末尾追加了 .domestic-labor-shell 相关样式
```

### 后端 API

```
bonus_platform/app.py
├── 第1340行起：payroll_logger、_run_payroll_calculation()
├── 第1364行：GET  /api/domestic-labor/runs          # 任务列表
├── 第1369行：POST /api/domestic-labor/runs          # 创建任务
├── 第1427行：GET  /api/domestic-labor/runs/{id}     # 任务状态
├── 第1436行：GET  /api/domestic-labor/runs/{id}/results   # 结果
├── 第1450行：GET  /api/domestic-labor/runs/{id}/export    # 导出
├── 第1467行：GET  /api/domestic-labor/runs/{id}/download/{filename}  # 下载
├── 第1482行：DELETE /api/domestic-labor/runs/{id}   # 删除
├── 第1492行：GET  /api/domestic-labor/templates     # 模板列表
└── 第1497行：GET  /api/domestic-labor/templates/{engine}/download  # 模板下载
```

### 计算引擎

```
bonus_platform/engine/domestic_labor/
├── __init__.py              # 导出4个引擎类
├── engines/
│   ├── __init__.py          # QuanQinJiangEngine, CanBuEngine, WaiSuBuTieEngine, GongLingJiangEngine
│   ├── base.py              # BaseEngine 基类，CalculationResult 数据类
│   ├── quanqinjiang.py      # 全勤奖引擎
│   ├── canbu.py             # 餐补引擎
│   ├── waisu_butie.py       # 外宿补贴引擎
│   └── gonglingjiang.py     # 工龄奖引擎
├── parser.py                # ExcelParser + PayrollDataLoader（数据加载与标准化）
├── templates.py             # ENGINE_TEMPLATES 定义 + generate_template()
├── exporter.py              # ExcelExporter（结果导出）
└── runs.py                  # 文件存储层（metadata.json 管理）
```

### 测试文件

```
tests/
├── test_domestic_labor_api.py   # 12个API测试用例
└── test_static_branding.py      # 15个静态资源测试（已更新）
```

### 配置

```
bonus_platform/config.py
└── DOMESTIC_LABOR_RUNS_DIR = OUTPUT_DIR / "domestic_labor_runs"
```

---

## 3. 业务流程

### 用户操作流程

```
1. 打开 domestic-labor.html
2. 选择计算引擎（可多选：全勤奖、餐补、外宿补贴、工龄奖）
3. 选择考勤月份（如 202606）
4. 上传 Excel 文件（.xlsx/.xlsm/.xls，可选密码）
5. 配置 HRBP 名单（可选，JSON数组格式，仅工龄奖揽收部需要）
6. 确认提交
7. 等待后台计算（轮询状态）
8. 查看结果 → 导出 Excel
```

### 系统处理流程

```
1. POST /api/domestic-labor/runs
   ├── 保存文件到 DOMESTIC_LABOR_RUNS_DIR/{run_id}/
   ├── 创建 metadata.json（状态=已上传）
   └── 启动后台线程 _run_payroll_calculation()

2. 后台计算
   ├── PayrollDataLoader 加载 Excel
   │   ├── 读取「月考勤」Sheet → monthly
   │   ├── 读取「日考勤」Sheet → daily_by_emp（按工号分组）
   │   └── 读取「住宿名单」Sheet → housing_by_emp（按工号分组）
   ├── 遍历 monthly.rows
   │   ├── QuanQinJiangEngine.calculate(row, daily)
   │   ├── CanBuEngine.calculate(row, daily)
   │   ├── WaiSuBuTieEngine.calculate(row, daily, housing)
   │   └── GongLingJiangEngine.calculate(row, hrbp_list)
   ├── 汇总 total = quanqinjiang + canbu + waisu_butie + gonglingjiang
   └── 保存 metadata.json（状态=已完成，results=[...]）

3. GET /api/domestic-labor/runs/{id}/export
   ├── ExcelExporter 生成3个Sheet
   │   ├── 计算详情：工号、姓名、部门、4项金额、合计、备注
   │   ├── 汇总统计：各引擎人数与金额
   │   └── 异常记录：有warnings的员工
   └── 保存到 outputs/payroll_outputs/
```

### 输出结果结构

```json
{
  "employee_id": "OWHN001",
  "employee_name": "张三",
  "department": "中国操作部",
  "quanqinjiang": 100.0,
  "canbu": 0,
  "waisu_butie": 0,
  "gonglingjiang": 0,
  "total": 100.0,
  "warnings": ""
}
```

---

## 4. 已实现薪酬项目的计算逻辑

### 4.1 全勤奖（QuanQinJiangEngine）

**规则**：100元/人/月

**排除条件**（任一命中则全勤奖=0）：
1. 硬编码排除名单：`OWHN9535`, `OWHN9353`, `OWHX0190`
2. 旷工天数 > 0
3. (正班迟到次数 + 早退次数) > 3
4. 签卡次数 > 3
5. 工伤假天数 > 0
6. 事假时数 > 0
7. 病假时数 > 0
8. 入离职缺勤时数 > 0
9. 迟到早退30分钟内扣款 > 0
10. 当月入职且入职前有工作日（需查日考勤判断gap期间是否有工作日）
11. 当月离职且未到月末

**特殊情况**：
- 入职日期在月中，但入职前全是休息日/节假日 → 不排除
- 最后工作日为空 → 视为在职
- Excel空值处理：`time(0,0)` 视为空，年份<1905的日期视为空

### 4.2 餐补（CanBuEngine）

**规则**：19元/天，封顶500元/月

**前置条件**：
- 「餐补标准」字段必须为 `"19元/天，封顶500元/月"`（精确匹配）
- 必须有日考勤数据

**日餐补计算**：
1. 优先使用日考勤中的预计算「餐补」值
2. 理货操作组 + 计件 → 0元
3. 旷工日 → 0元
4. 有效时数 = max(正班时数, 刷卡加班)
5. 有效时数 > 8小时 → 19元
6. 有效时数 = 0 → 0元
7. 其他 → 有效时数 × (19/8)

**月汇总**：sum(日餐补)，封顶500元

### 4.3 外宿补贴（WaiSuBuTieEngine）

**规则**：150元/月，按在职天数折算

**前置条件**：
- 「外宿补贴标准」字段不为 "/" 或空
- 不能全月未出勤

**计算公式**：
1. 计算在职天数 = (min(最后工作日, 月末) - max(入职日期, 月初) + 1)
2. 住宿扣除天数：根据「住宿名单」Sheet 的入住/退宿时间计算重叠天数
3. 外宿补贴天数 = 在职天数 - 住宿扣除天数
4. 缺勤时数 = 事假 + 排休请假 + 病假 + 旷工 + 入离职缺勤
5. 如果全月在职 且 缺勤≥56小时 且 无住宿扣除：
   - 有效天数 = 当月天数 - 缺勤时数/8
   - 补贴 = 150/当月天数 × 有效天数
6. 否则：
   - 补贴 = 150/当月天数 × 外宿补贴天数

### 4.4 工龄奖（GongLingJiangEngine）

**规则**：按工龄×标准，有上限

**区域区分**：
- 莞深广珠（默认）：操作/揽收 150元/年（上限600），FBU 100元/年（上限500）
- 华西华东东南：统一 50元/年（上限150）

**部门映射**（莞深广珠）：
- 中国操作部 → 操作
- 第四纵队 → 揽收
- 头程运营部 → FBU

**岗位资格**（莞深广珠操作部）：
内勤专员、中转员、门禁员、操作员、监察员、安检员、操作文员、查验员、叉车司机、揽收充电司机

**计算公式**：
1. 工龄 = 当前年 - 入职年（如果当月日期 < 入职月日则减1）
2. 应发 = min(标准 × 工龄, 上限)
3. 如果请假时数 ≥ 56小时：
   - 日薪 = 应发 / 排班天数
   - 扣减后 = 日薪 × (排班天数 - 请假时数/8)
4. 入离职缺勤扣减 = 日薪 × (入离职缺勤时数/8)
5. 最终 = min(扣减后 - 入离职缺勤扣减, 上限)

**揽收部特殊处理**：
- 需要HRBP发放名单（工号列表）
- 名单中且非组长 → 有工龄奖
- 名单为空时 → 返回warning提示提供名单

---

## 5. 规则假设与来源

### 明确给定的规则（来自用户/需求文档）

| 规则 | 来源 |
|------|------|
| 全勤奖 100元/人/月 | 用户明确指定 |
| 全勤奖排除条件（旷工、迟到>3次、签卡>3次等） | 用户明确指定 |
| 餐补 19元/天，封顶500元/月 | 用户明确指定 |
| 外宿补贴 150元/月 | 用户明确指定 |
| 工龄奖莞深广珠标准（操作/揽收150元/年，FBU 100元/年） | 用户明确指定 |
| 工龄奖华西华东东南标准（50元/年，上限150） | 用户明确指定 |
| 工龄奖排除岗位（组长类） | 用户明确指定 |
| 硬编码排除名单（OWHN9535等） | 用户明确指定 |

### 临时推断/假设的规则

| 规则 | 假设依据 | 风险 |
|------|----------|------|
| 入职前gap全是休息日则不排除全勤奖 | 合理推断，需业务确认 | 中 |
| 事假时数>0即排除全勤奖（无论时长） | 严格解释，需确认是否有时长阈值 | 中 |
| 餐补日计算公式（有效时数/8 × 19） | 线性折算假设，需确认是否按小时四舍五入 | 低 |
| 外宿补贴缺勤≥56小时才触发折算 | 来自原始需求，但阈值需确认 | 低 |
| 工龄奖请假≥56小时才扣减 | 与外宿补贴逻辑一致，需确认 | 中 |
| 工龄奖允许负数（需从工资扣除） | 合理推断，需确认是否允许 | 高 |
| 区域自动检测（华东/华西 → wes区域） | 简单关键词匹配，可能误判 | 中 |
| 东莞数据加载器（DongguanDataLoader）已实现但未接入 | 代码存在但未在主流程使用 | 低 |

---

## 6. 样例数据与测试方式

### 测试数据

**模板文件**（可从 API 下载）：
- `GET /api/domestic-labor/templates/quanqinjiang/download`
- `GET /api/domestic-labor/templates/canbu/download`
- `GET /api/domestic-labor/templates/waisu_butie/download`
- `GET /api/domestic-labor/templates/gonglingjiang/download`

**API 测试中使用的数据**：
```python
# test_domestic_labor_api.py 中的 _quanqinjiang_data()
全勤奖 Sheet:
| 工号    | 姓名 | 考勤月份 | 入职日期   | 最后工作日 | 旷工天数 | 迟到次数 | 早退次数 | 签卡次数 | 工伤假 | 事假时数 | 病假时数 | 入离职缺勤 | 扣款 |
|---------|------|----------|------------|------------|----------|----------|----------|----------|--------|----------|----------|------------|------|
| OWHN001 | 张三 | 202606   | 2023-01-15 |            | 0        | 0        | 0        | 0        | 0      | 0        | 0        | 0          | 0    |
| OWHN002 | 李四 | 202606   | 2022-06-01 |            | 1        | 0        | 0        | 0        | 0      | 0        | 0        | 0          | 0    |
```

### 运行测试

```bash
cd /Users/zt27532/Documents/New\ project\ 2

# 运行API测试
python3 -m pytest tests/test_domestic_labor_api.py -v

# 运行静态资源测试
python3 -m pytest tests/test_static_branding.py -v

# 运行全部测试
python3 -m pytest tests/ -v
```

### 预期结果

```
test_domestic_labor_api.py  ✅ 12 passed
test_static_branding.py     ✅ 15 passed
```

### 手动测试流程

```bash
# 1. 启动服务
cd bonus_platform
python3 -m uvicorn app:app --reload

# 2. 浏览器打开
http://127.0.0.1:8000/domestic-labor.html

# 3. 选择引擎 → 上传模板文件 → 确认计算 → 查看结果
```

---

## 7. 已知问题与风险点

### 高风险

| 问题 | 影响 | 建议 |
|------|------|------|
| 工龄奖允许负数 | 可能导致员工被扣款，需业务确认 | 与HR确认是否允许，如不允许需加 `max(0, final)` |
| 餐补/外宿补贴测试数据返回0 | 模板字段与引擎期望字段不完全匹配 | 需用真实考勤数据验证 |

### 中风险

| 问题 | 影响 | 建议 |
|------|------|------|
| 区域自动检测逻辑简单 | 可能误判华东/华西员工 | 建议增加「区域」字段或配置化 |
| 事假>0即排除全勤奖 | 可能过于严格（如有0.5小时事假） | 与HR确认是否有阈值 |
| 工龄奖请假≥56小时阈值 | 与外宿补贴一致，但未确认 | 需业务确认 |
| DongguanDataLoader 未接入 | 东莞区域餐补标准逻辑未生效 | 需要时再接入 |

### 低风险

| 问题 | 影响 | 建议 |
|------|------|------|
| Excel密码解密依赖 msoffcrypto | 未安装时无法处理加密文件 | requirements.txt 已包含 |
| 大文件内存占用 | read_only=True 已优化 | 无需处理 |
| 任务目录无清理机制 | 长期运行会占用磁盘 | 可加定期清理脚本 |

---

## 8. 下一步建议（按优先级）

### P0 - 必须做

1. **用真实考勤数据端到端验证**
   - 找HR要一份真实的月考勤Excel（含日考勤、住宿名单）
   - 验证4个引擎都能正确计算
   - 特别关注餐补和外宿补贴是否返回非0值

2. **确认工龄奖负数处理**
   - 与HR确认：请假过多时工龄奖是否允许为负（需从工资扣除）
   - 如不允许，修改 `gonglingjiang.py` 最后一行加 `max(0, final)`

3. **确认全勤奖事假阈值**
   - 当前逻辑：事假时数 > 0 即排除
   - 与HR确认是否有最低阈值（如事假≤2小时不影响）

### P1 - 应该做

4. **增加数据校验层**
   - 上传时检查列名是否匹配模板
   - 检查必填字段是否为空
   - 返回友好的错误提示

5. **完善餐补引擎的简化模式**
   - 当前测试数据中餐补返回0，因为依赖日考勤数据
   - 考虑增加「预计算餐补」字段的优先使用逻辑（已在代码中，需验证）

6. **增加前端结果筛选和排序**
   - 当前结果表格无筛选功能
   - 可增加：按引擎筛选、按金额排序、搜索员工

### P2 - 可以做

7. **东莞数据加载器接入**
   - `DongguanDataLoader` 已实现但未在主流程使用
   - 如有东莞区域需求，需在 `_run_payroll_calculation` 中接入

8. **扣款/补发引擎**
   - 当前扣款逻辑分散在各引擎的排除条件中
   - 如需独立扣款计算，需新建引擎

9. **历史版本比对**
   - 跨月对比薪酬变化
   - 需要数据持久化和查询接口

10. **批量任务管理**
    - 批量删除、批量导出
    - 任务搜索和筛选

---

## 9. 代码规范提醒

### 不要做的事

- 不要重构 `parser.py` 中的 `PayrollDataLoader`，它处理了很多边界情况
- 不要修改 `runs.py` 中的文件存储逻辑，它与其他模块（labor、recruitment）保持一致
- 不要删除 `DongguanDataLoader`，虽然未接入但代码是正确的

### 代码风格

- 引擎类继承 `BaseEngine`，实现 `calculate()` 和 `calculate_batch()`
- 返回 `CalculationResult` 数据类（含 employee_id, employee_name, amount, details, warnings）
- warnings 用列表收集，最后 join 成字符串
- 数值计算用 `safe_float()` 和 `safe_int()` 避免类型错误

---

## 10. 快速上手指南

### 新工程师第一天

1. 阅读本文档
2. 运行测试：`python3 -m pytest tests/test_domestic_labor_api.py -v`
3. 启动服务：`cd bonus_platform && python3 -m uvicorn app:app --reload`
4. 打开浏览器：`http://127.0.0.1:8000/domestic-labor.html`
5. 下载模板，用模板数据测试完整流程

### 修改引擎时

1. 先看 `engines/base.py` 了解 `CalculationResult` 结构
2. 修改对应的引擎文件
3. 在 `templates.py` 中更新模板列定义（如有新增字段）
4. 在 `app.py` 的 `_run_payroll_calculation()` 中更新调用逻辑
5. 运行测试验证

### 新增引擎时

1. 在 `engines/` 下新建文件，继承 `BaseEngine`
2. 在 `engines/__init__.py` 中导出
3. 在 `templates.py` 中添加模板定义
4. 在 `app.py` 的 `_run_payroll_calculation()` 中添加调用
5. 在 `domestic-labor.js` 的 `ENGINE_META` 中添加前端配置
6. 在 `styles.css` 中添加对应的KPI颜色
7. 添加测试用例

---

*文档结束。如有疑问，请联系原负责人或查阅代码注释。*
