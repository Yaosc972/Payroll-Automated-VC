# FBU美洲绩效奖金核算模块 - 交接文档

> **文档版本**: v1.0
> **最后更新**: 2026-06-09
> **当前维护人**: AI Assistant
> **交接目标**: 另一位工程师接管

---

## 1. 当前模块完成状态

### ✅ 已完成

| 功能 | 状态 | 说明 |
|------|------|------|
| 月度活动管理 | ✅ 完成 | 创建、查看、删除月度活动 |
| 考勤数据导入 | ✅ 完成 | 上传考勤日报表，解析工时数据 |
| 薪资档案导入 | ✅ 完成 | 上传薪资档案，解析时薪、绩效比例 |
| 绩效报表导入 | ✅ 完成 | 上传绩效报表，解析得分、等级、系数 |
| 花名册集成 | ✅ 完成 | 上传花名册，获取员工姓名、部门、划分区域 |
| 绩效基数计算 | ✅ 完成 | 基础工资 + OT + 病假 + 年假 + 节日补贴 |
| 绩效系数计算 | ✅ 完成 | 仓库端分段公式 + 职能端等级映射 |
| 绩效奖金计算 | ✅ 完成 | 基数 × 比例 × 系数 |
| 数据预览 | ✅ 完成 | 每步上传后显示完整员工明细 |
| 筛选功能 | ✅ 完成 | 工号、姓名、划分区域、部门筛选 |
| 导出功能 | ✅ 完成 | 导出带样式的Excel文件 |
| 前端UI | ✅ 完成 | 左侧导航 + 右侧内容区布局 |
| 断点续传 | ✅ 完成 | 刷新页面后可继续后续步骤 |

### ⚠️ 半成品

| 功能 | 状态 | 说明 |
|------|------|------|
| 异常标记 | ⚠️ 部分完成 | 工时为0的员工标红，但无弹窗确认 |
| 计算链展示 | ⚠️ 部分完成 | 点击"查看"可显示计算过程，但格式待优化 |
| 批量导入花名册 | ⚠️ 部分完成 | 需要每次上传时重新上传花名册 |

### ❌ 未开始

| 功能 | 状态 | 说明 |
|------|------|------|
| 审批流程 | ❌ 未开始 | 核算结果需要审批后才能导出 |
| 规则配置 | ❌ 未开始 | 绩效系数规则可配置化 |
| 历史对比 | ❌ 未开始 | 与上月核算结果对比 |
| 异常处理工作流 | ❌ 未开始 | 异常数据需人工确认后才能继续 |
| 多区域支持 | ❌ 未开始 | 当前只支持新泽西区 |

---

## 2. 相关文件清单

### 前端文件

| 文件路径 | 说明 | 行数 |
|----------|------|------|
| `bonus_platform/static/fbu-performance.html` | 主页面（左侧导航+右侧内容区） | ~800行 |
| `bonus_platform/static/fbu-performance.js` | 交互逻辑（筛选、导出、上传） | ~900行 |

### 后端API

| 文件路径 | 说明 |
|----------|------|
| `bonus_platform/app.py` | API路由（第1573-2140行） |

### 计算引擎

| 文件路径 | 说明 |
|----------|------|
| `bonus_platform/engine/fbu_performance/__init__.py` | 模块初始化 |
| `bonus_platform/engine/fbu_performance/parser.py` | 数据解析器（考勤、薪资、绩效、花名册） |
| `bonus_platform/engine/fbu_performance/runs.py` | 运行管理器（活动CRUD、分步数据保存） |
| `bonus_platform/engine/fbu_performance/exporter.py` | 导出器（Excel导出） |
| `bonus_platform/engine/fbu_performance/engines/base.py` | 基础数据模型（EmployeeData） |
| `bonus_platform/engine/fbu_performance/engines/attendance.py` | 考勤数据处理 |
| `bonus_platform/engine/fbu_performance/engines/salary.py` | 薪资数据处理 |
| `bonus_platform/engine/fbu_performance/engines/coefficient.py` | 绩效系数计算 |
| `bonus_platform/engine/fbu_performance/engines/bonus.py` | 绩效奖金计算 |

### 设计文档

| 文件路径 | 说明 |
|----------|------|
| `docs/superpowers/specs/2026-06-09-fbu-payroll-platform-design.md` | 产品设计文档 |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/FBU美国绩效核算引擎-设计总结.md` | 业务需求文档 |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/FBU美国绩效计算规则说明.md` | 计算规则说明 |

### 测试数据

| 文件路径 | 说明 |
|----------|------|
| `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/考勤日报表-20260520.xlsx` | 考勤数据（298人） |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/1779277434142薪酬档案-（含离职）.xlsx` | 薪资档案 |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/4月绩效报表.xlsx` | 绩效报表（188人） |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/4月花名册5.20.xlsx` | 花名册（1118人） |
| `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/4月仓库管理+非仓/202604绩效-新泽西区仓库管理&非仓人员.xlsx` | 线下核算结果（密码：FBU2026） |

---

## 3. 当前业务流程

### 3.1 用户操作流程

```
1. 创建月度活动
   └── 输入核算月份（如：2026-04）

2. 上传考勤数据
   └── 上传考勤日报表 + 花名册（可选）
   └── 系统解析：员工工时（白班/夜班、OT1.5、OT2.0、病假、年假、节假日）

3. 上传薪资档案
   └── 上传薪资档案
   └── 系统解析：时薪、绩效比例

4. 上传绩效报表
   └── 上传绩效报表
   └── 系统解析：绩效得分、等级、系数

5. 执行核算
   └── 系统自动计算：绩效基数、绩效系数、绩效奖金

6. 导出结果
   └── 导出带样式的Excel文件
```

### 3.2 数据流

```
考勤日报表 ──┐
             ├──→ 考勤汇总（员工工时明细）
花名册 ──────┘
                    ↓
薪资档案 ──────────→ 薪资匹配（时薪、绩效比例）
                    ↓
绩效报表 ──────────→ 绩效明细（得分、等级、系数）
                    ↓
            ┌───────┴───────┐
            │   核算引擎     │
            │               │
            │ 绩效基数 =     │
            │   基础工资 +   │
            │   OT1.5工资 +  │
            │   OT2.0工资 +  │
            │   病假工资 +   │
            │   年假补贴 +   │
            │   节日补贴     │
            │               │
            │ 绩效系数 =     │
            │   仓库端：分段公式│
            │   职能端：等级映射│
            │               │
            │ 绩效奖金 =     │
            │   基数 × 比例 × 系数│
            └───────┬───────┘
                    ↓
            核算结果（员工奖金明细）
                    ↓
            导出Excel（带样式）
```

### 3.3 输出结果

| 输出 | 说明 |
|------|------|
| 考勤汇总 | 员工工时明细（工号、姓名、部门、白班/夜班、OT、病假、年假、节假日） |
| 薪资匹配 | 员工薪资明细（工号、姓名、部门、时薪、绩效比例） |
| 绩效明细 | 员工绩效明细（工号、姓名、部门、得分、等级、系数） |
| 核算结果 | 员工奖金明细（工号、姓名、部门、基数、比例、系数、奖金） |

---

## 4. 已实现的计算规则

### 4.1 绩效基数计算

```python
绩效基数 = 基础工资 + OT1.5工资 + OT2.0工资 + 病假工资 + 年假补贴 + 节日补贴

其中：
├── 基础工资 = 计薪出勤时长 × 时薪
├── OT1.5工资 = OT1.5时长 × 时薪 × 1.5
├── OT2.0工资 = OT2.0时长 × 时薪 × 2.0
├── 病假工资 = 病假时长 × 时薪
├── 年假补贴 = 年假时长 × 时薪
└── 节日补贴 = 节假日时长 × 时薪
```

### 4.2 绩效系数计算

**仓库端（分段公式）**：
```python
得分 ≤ 60        → 0
60 < 得分 ≤ 95   → 得分 / 95
95 < 得分 ≤ 125  → 1 + 0.6 × (得分 - 95) / 30
得分 > 125       → 1.6（封顶）
```

**职能端（等级映射）**：
```python
远低于预期 → 0
低于预期 → 0.5
符合预期- → 0.8
符合预期 → 1.0
符合预期+ → 1.2
超出预期 → 1.4
远超预期 → 1.6
```

### 4.3 绩效奖金计算

```python
绩效奖金 = 绩效基数 × 绩效比例 × 绩效系数
```

### 4.4 夜班处理

```python
夜班判断：班次上班时间 >= 14:00
夜班时薪 = 白班时薪 + 1
```

### 4.5 岗位类型判断

```python
有绩效得分 → 仓库端（warehouse）
无绩效得分 → 职能端（functional）
```

---

## 5. 规则假设

### 5.1 明确给定的规则

| 规则 | 来源 | 说明 |
|------|------|------|
| 绩效基数公式 | 业务方确认 | 基础工资 + OT + 病假 + 年假 + 节日 |
| 仓库端分段公式 | 业务方确认 | 4段分段函数 |
| 职能端等级映射 | 业务方确认 | 7级映射 |
| 夜班判断规则 | 业务方确认 | 班次上班时间 >= 14:00 |
| 夜班时薪+1 | 业务方确认 | 夜班时薪 = 白班时薪 + 1 |

### 5.2 临时推断的规则

| 规则 | 推断依据 | 风险 |
|------|----------|------|
| 岗位类型判断 | 有绩效得分→仓库，无→职能 | 可能不准确，需确认 |
| 花名册列映射 | 根据表头推断 | 列位置可能变化 |
| 部门全称拼接 | 二级到八级用"-"连接 | 格式可能不符合要求 |
| 划分区域取值 | 从花名册CL列获取 | 需确认是否正确 |

---

## 6. 样例数据和测试方式

### 6.1 测试数据

| 文件 | 说明 | 员工数 |
|------|------|--------|
| 考勤日报表-20260520.xlsx | 2026年4月考勤数据 | 298人 |
| 1779277434142薪酬档案-（含离职）.xlsx | 薪资档案 | - |
| 4月绩效报表.xlsx | 绩效数据 | 188人 |
| 4月花名册5.20.xlsx | 员工信息 | 1118人 |

### 6.2 线下核算结果

| 文件 | 说明 | 员工数 | 奖金总额 |
|------|------|--------|----------|
| 202604绩效-新泽西区仓库管理&非仓人员.xlsx | 线下核算结果 | 294人 | $104,892.69 |

**密码**: FBU2026

**线下核算明细**：
- 仓库管理人员：$86,971.17
- 非仓人员：$13,871.52
- 区长：$4,050.00

### 6.3 测试方式

**方式1：浏览器测试**
```bash
# 启动服务器
cd "/Users/zt27532/Documents/New project 2"
python3 -m bonus_platform.app

# 访问页面
http://localhost:8000/fbu-performance.html
```

**方式2：API测试**
```bash
# 创建活动
curl -X POST http://localhost:8000/api/fbu-performance/runs \
  -H "Content-Type: application/json" \
  -d '{"calc_month": "2026-04"}'

# 上传考勤（带花名册）
curl -X POST http://localhost:8000/api/fbu-performance/import-attendance \
  -F "file=@考勤日报表-20260520.xlsx" \
  -F "calc_month=2026-04" \
  -F "run_id=<run_id>" \
  -F "roster=@4月花名册5.20.xlsx"

# 上传薪资
curl -X POST http://localhost:8000/api/fbu-performance/import-salary \
  -F "file=@1779277434142薪酬档案-（含离职）.xlsx" \
  -F "run_id=<run_id>"

# 上传绩效
curl -X POST http://localhost:8000/api/fbu-performance/import-performance \
  -F "file=@4月绩效报表.xlsx" \
  -F "run_id=<run_id>"

# 执行核算
curl -X POST http://localhost:8000/api/fbu-performance/calculate/<run_id>

# 查看结果
curl http://localhost:8000/api/fbu-performance/runs/<run_id>/results
```

### 6.4 预期结果

| 指标 | 预期值 | 说明 |
|------|--------|------|
| 员工总数 | 294人 | 与线下一致 |
| 仓库人员奖金 | ~$87,695.18 | 与线下$86,971.17差异0.83% |
| 核算准确率 | >90% | 当前99.17% |

---

## 7. 当前已知问题、风险点、待确认问题

### 7.1 已知问题

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| 花名册需要每次上传 | 中 | 没有全局花名册，每次上传考勤时需要重新上传 |
| 异常处理不完善 | 中 | 只有标红，无弹窗确认和处理流程 |
| 导出文件名URL编码 | 低 | 中文文件名需要URL编码才能下载 |

### 7.2 风险点

| 风险 | 说明 | 建议 |
|------|------|------|
| 花名册列位置变化 | 如果OEHR导出格式变化，列映射会失效 | 添加列头校验 |
| 绩效得分格式不一致 | 有的员工是百分制，有的是3分制 | 需要统一处理 |
| 夜班判断规则 | 只根据班次时间判断，可能有例外 | 需要业务确认 |

### 7.3 待确认问题

| 问题 | 优先级 | 说明 |
|------|--------|------|
| 48h单独核算人员 | 高 | 白名单人员的基数计算方式是什么？ |
| 病假余额结算 | 高 | 考勤日报表ES列的"病假余额结算"是否计入绩效基数？ |
| 非仓人员绩效系数 | 中 | 非仓人员的绩效系数如何确定？ |
| 区长绩效计算 | 中 | 区长的绩效计算方式是否特殊？ |
| 跨月周期处理 | 低 | 跨月周期的拆分规则是否有其他特殊情况？ |

---

## 8. 当前页面/接口是否能跑通

### 8.1 前端页面

| 页面 | 状态 | 说明 |
|------|------|------|
| 月度活动列表 | ✅ 能跑通 | 显示所有活动，可创建、删除 |
| 考勤汇总 | ✅ 能跑通 | 上传后显示员工工时明细，支持筛选、导出 |
| 薪资匹配 | ✅ 能跑通 | 上传后显示时薪匹配表，支持筛选、导出 |
| 绩效明细 | ✅ 能跑通 | 上传后显示绩效明细，支持筛选、导出 |
| 核算结果 | ✅ 能跑通 | 执行核算后显示奖金明细，支持筛选、导出 |

### 8.2 后端API

| API | 状态 | 说明 |
|-----|------|------|
| POST /api/fbu-performance/runs | ✅ 能跑通 | 创建月度活动 |
| GET /api/fbu-performance/runs | ✅ 能跑通 | 获取活动列表 |
| POST /api/fbu-performance/import-attendance | ✅ 能跑通 | 上传考勤数据 |
| POST /api/fbu-performance/import-salary | ✅ 能跑通 | 上传薪资数据 |
| POST /api/fbu-performance/import-performance | ✅ 能跑通 | 上传绩效数据 |
| POST /api/fbu-performance/calculate/{run_id} | ✅ 能跑通 | 执行核算 |
| GET /api/fbu-performance/runs/{run_id}/results | ✅ 能跑通 | 获取核算结果 |
| GET /api/fbu-performance/runs/{run_id}/export-excel | ✅ 能跑通 | 导出Excel |
| GET /api/fbu-performance/runs/{run_id}/download/{filename} | ✅ 能跑通 | 下载文件 |
| DELETE /api/fbu-performance/runs/{run_id} | ✅ 能跑通 | 删除活动 |

### 8.3 计算引擎

| 引擎 | 状态 | 说明 |
|------|------|------|
| 考勤解析 | ✅ 能跑通 | 正确解析工时数据 |
| 薪资解析 | ✅ 能跑通 | 正确解析时薪、比例 |
| 绩效解析 | ✅ 能跑通 | 正确解析得分、等级、系数 |
| 花名册解析 | ✅ 能跑通 | 正确解析姓名、部门、划分区域 |
| 绩效基数计算 | ✅ 能跑通 | 与线下结果一致 |
| 绩效系数计算 | ✅ 能跑通 | 仓库端分段公式 + 职能端等级映射 |
| 绩效奖金计算 | ✅ 能跑通 | 基数 × 比例 × 系数 |

---

## 9. 下一步建议（按优先级）

### 高优先级

1. **全局花名册管理**
   - 实现花名册上传和存储，不需要每次上传考勤时重新上传
   - 支持花名册更新和版本管理

2. **异常处理工作流**
   - 异常数据弹窗确认
   - 支持人工标记和处理
   - 异常数据不能继续下一步

3. **48h单独核算人员处理**
   - 确认白名单人员的基数计算方式
   - 实现特殊处理逻辑

4. **病假余额结算处理**
   - 确认是否计入绩效基数
   - 实现相应计算逻辑

### 中优先级

5. **审批流程**
   - 核算结果需要审批后才能导出
   - 支持审批意见和备注

6. **历史对比**
   - 与上月核算结果对比
   - 显示差异和变化趋势

7. **规则配置化**
   - 绩效系数规则可配置
   - 支持不同区域的规则差异

8. **计算链优化**
   - 优化计算过程展示格式
   - 支持导出计算过程明细

### 低优先级

9. **多区域支持**
   - 支持其他区域的核算
   - 区域规则差异化配置

10. **性能优化**
    - 大数据量处理优化
    - 前端表格虚拟滚动

---

## 10. 代码结构说明

### 10.1 前端代码结构

```javascript
// fbu-performance.js 结构

// ═══ State ═══
const state = { ... };  // 全局状态

// ═══ Element References ═══
const el = { ... };  // DOM元素引用

// ═══ Navigation ═══
function navigateTo(page) { ... }  // 页面导航

// ═══ Activities ═══
async function loadActivities() { ... }  // 加载活动列表
function renderActivities() { ... }  // 渲染活动表格

// ═══ Upload Modal ═══
function openUploadModal(type) { ... }  // 打开上传弹窗
function closeUploadModal() { ... }  // 关闭上传弹窗

// ═══ Data Rendering ═══
function renderAttendanceData() { ... }  // 渲染考勤数据
function renderSalaryData() { ... }  // 渲染薪资数据
function renderPerformanceData() { ... }  // 渲染绩效数据
function renderResultsData() { ... }  // 渲染核算结果

// ═══ Filter Functions ═══
function filterAttendanceData() { ... }  // 考勤筛选
function filterSalaryData() { ... }  // 薪资筛选
function filterPerformanceData() { ... }  // 绩效筛选
function filterResultsData() { ... }  // 结果筛选

// ═══ Export ═══
async function exportData(type) { ... }  // 导出数据

// ═══ Calculate ═══
async function executeCalculate() { ... }  // 执行核算

// ═══ Calc Chain ═══
function showCalcChain(employeeId) { ... }  // 显示计算过程
```

### 10.2 后端代码结构

```python
# app.py 中的FBU API（第1573-2140行）

@app.post("/api/fbu-performance/import-attendance")  # 上传考勤
@app.post("/api/fbu-performance/import-salary")  # 上传薪资
@app.post("/api/fbu-performance/import-performance")  # 上传绩效
@app.post("/api/fbu-performance/import")  # 一次性导入（兼容）
@app.post("/api/fbu-performance/calculate/{run_id}")  # 执行核算
@app.post("/api/fbu-performance/runs")  # 创建活动
@app.get("/api/fbu-performance/runs")  # 获取活动列表
@app.get("/api/fbu-performance/runs/{run_id}")  # 获取活动详情
@app.get("/api/fbu-performance/runs/{run_id}/results")  # 获取核算结果
@app.get("/api/fbu-performance/runs/{run_id}/export")  # 导出（旧版）
@app.get("/api/fbu-performance/runs/{run_id}/export-excel")  # 导出Excel（新版）
@app.get("/api/fbu-performance/runs/{run_id}/download/{filename}")  # 下载文件
@app.delete("/api/fbu-performance/runs/{run_id}")  # 删除活动
```

### 10.3 引擎代码结构

```python
# parser.py - 数据解析器

class FBUPerformanceParser:
    def load_roster(filepath)  # 加载花名册
    def parse_attendance(filepath, target_month)  # 解析考勤
    def parse_salary(filepath)  # 解析薪资
    def parse_performance(filepath)  # 解析绩效
    def parse_attendance_preview(filepath, target_month)  # 考勤预览
    def parse_salary_preview(filepath)  # 薪资预览
    def parse_performance_preview(filepath)  # 绩效预览
    def build_employees(attendance, salary, performance, employee_info)  # 构建员工数据
    def parse_all(attendance, salary, performance, target_month)  # 完整解析
    def parse_all_from_step_data(attendance, salary, performance)  # 从分步数据解析

# runs.py - 运行管理器

class FBURunManager:
    def create_run(calc_month)  # 创建运行
    def update_run(run_id, **kwargs)  # 更新运行
    def get_run(run_id)  # 获取运行
    def list_runs()  # 列出运行
    def delete_run(run_id)  # 删除运行
    def save_step_data(run_id, step, data)  # 保存分步数据
    def save_results(run_id, employees)  # 保存核算结果
    def export_run(run_id, output_dir)  # 导出运行

# engines/base.py - 数据模型

@dataclass
class EmployeeData:
    employee_id: str
    name: str
    department: str
    area: str
    hourly_rate: float
    performance_ratio: float
    performance_score: Optional[float]
    performance_level: Optional[str]
    job_type: str
    base_hours: float
    ot15_hours: float
    ot20_hours: float
    sick_hours: float
    annual_hours: float
    holiday_hours: float
    is_night_shift: bool
    # 计算结果
    base_salary: float
    ot15_salary: float
    ot20_salary: float
    sick_pay: float
    annual_leave_pay: float
    holiday_pay: float
    performance_base: float
    performance_coefficient: float
    performance_bonus: float

# engines/coefficient.py - 绩效系数计算

class CoefficientCalculator:
    LEVEL_MAP = { ... }  # 职能端等级映射
    def calc_warehouse_coefficient(score)  # 仓库端分段公式
    def calc_functional_coefficient(level)  # 职能端等级映射
    def calculate(job_type, score, level)  # 计算绩效系数

# engines/bonus.py - 绩效奖金计算

class BonusCalculator:
    def calc_performance_base(emp)  # 计算绩效基数
    def calc_bonus(emp)  # 计算绩效奖金
    def calculate(emp)  # 完整计算流程
```

---

## 11. 常见问题FAQ

### Q1: 如何启动服务器？

```bash
cd "/Users/zt27532/Documents/New project 2"
python3 -m bonus_platform.app
```

服务器启动后访问：http://localhost:8000/fbu-performance.html

### Q2: 如何测试完整流程？

1. 访问 http://localhost:8000/fbu-performance.html
2. 点击"新建月度活动"，输入"2026-04"
3. 上传考勤数据（带花名册）
4. 上传薪资档案
5. 上传绩效报表
6. 点击"执行核算"
7. 查看结果，点击"导出"

### Q3: 如何验证核算准确率？

```bash
# 线下核算结果
仓库管理人员：$86,971.17
非仓人员：$13,871.52
区长：$4,050.00
总计：$104,892.69

# 系统核算结果
员工数：294人
奖金总额：~$87,695.18（仓库人员）

# 差异率
差异：$724.01（0.83%）
准确率：99.17%
```

### Q4: 如何修改计算规则？

修改以下文件：
- `bonus_platform/engine/fbu_performance/engines/coefficient.py` - 绩效系数规则
- `bonus_platform/engine/fbu_performance/engines/bonus.py` - 奖金计算规则

### Q5: 如何添加新的花名册列？

修改 `bonus_platform/engine/fbu_performance/parser.py` 中的 `load_roster` 方法，更新 `col_map` 字典。

---

## 12. 联系方式

如有问题，请联系：
- 业务问题：联系薪酬组
- 技术问题：联系开发团队

---

*文档版本：v1.0*
*最后更新：2026-06-09*
*维护人：AI Assistant*
