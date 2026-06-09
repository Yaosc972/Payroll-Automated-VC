# FBU绩效模块分步导入改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将FBU绩效核算模块从一次性导入三个文件改造为5步wizard分步导入流程，每步上传后显示完整员工明细预览，并支持断点续传。

**Architecture:** 
- 前端采用wizard drawer模式（参考domestic-labor.html），5个步骤面板切换
- 后端新增3个独立上传API，每个API返回该步骤的数据预览
- 引擎层新增preview方法，返回完整员工明细而非汇总
- RunManager支持分步数据持久化，实现断点续传

**Tech Stack:** Python 3.x, FastAPI, openpyxl, msoffcrypto, HTML/CSS/JavaScript

---

## 文件结构

| 文件 | 职责 | 改动类型 |
|------|------|----------|
| `bonus_platform/engine/fbu_performance/runs.py` | 运行数据管理，支持分步数据持久化 | Modify |
| `bonus_platform/engine/fbu_performance/parser.py` | 数据解析，新增preview方法 | Modify |
| `bonus_platform/app.py` | API路由，新增3个分步导入端点 | Modify |
| `bonus_platform/static/fbu-performance.html` | 前端页面，重写为wizard模式 | Rewrite |
| `bonus_platform/static/fbu-performance.js` | 前端逻辑，重写为分步交互 | Rewrite |

---

## Task 1: 改造 RunManager 支持分步数据

**Files:**
- Modify: `bonus_platform/engine/fbu_performance/runs.py:15-28`

- [ ] **Step 1: 扩展 FBURun 数据结构**

在 `runs.py` 的 `FBURun` dataclass 中添加分步数据字段：

```python
@dataclass
class FBURun:
    """FBU核算运行记录"""
    run_id: str
    created_at: str
    calc_month: str
    status: str = "pending"  # pending / step1 / step2 / step3 / processing / completed / failed
    current_step: int = 0  # 当前步骤 (0=未开始, 1=考勤, 2=薪资, 3=绩效, 4=计算中, 5=完成)
    attendance_file: str = ""
    salary_file: str = ""
    performance_file: str = ""
    # 分步数据
    attendance_data: dict = field(default_factory=dict)  # 考勤解析结果
    salary_data: dict = field(default_factory=dict)  # 薪资解析结果
    performance_data: dict = field(default_factory=dict)  # 绩效解析结果
    # 最终结果
    total_employees: int = 0
    total_bonus: float = 0.0
    match_rate: float = 0.0
    results: list[dict] = field(default_factory=list)
    error: str = ""
```

- [ ] **Step 2: 修改 create_run 方法使文件参数可选**

```python
def create_run(
    self,
    calc_month: str,
    attendance_file: str = "",
    salary_file: str = "",
    performance_file: str = "",
) -> FBURun:
    """创建新的运行"""
    run = FBURun(
        run_id=str(uuid.uuid4())[:8],
        created_at=datetime.now().isoformat(),
        calc_month=calc_month,
        attendance_file=attendance_file,
        salary_file=salary_file,
        performance_file=performance_file,
    )
    self.runs[run.run_id] = run
    self._save_runs()
    return run
```

- [ ] **Step 3: 添加 save_step_data 方法**

在 `update_run` 方法之后添加：

```python
def save_step_data(self, run_id: str, step: int, data: dict):
    """保存分步数据"""
    run = self.get_run(run_id)
    if not run:
        return

    if step == 1:
        run.attendance_data = data
        run.current_step = 1
        run.status = "step1"
    elif step == 2:
        run.salary_data = data
        run.current_step = 2
        run.status = "step2"
    elif step == 3:
        run.performance_data = data
        run.current_step = 3
        run.status = "step3"

    self._save_runs()
```

- [ ] **Step 4: 提交**

```bash
git add bonus_platform/engine/fbu_performance/runs.py
git commit -m "feat(fbu-performance): extend FBURun to support step-by-step data persistence"
```

---

## Task 2: 添加数据预览方法到 Parser

**Files:**
- Modify: `bonus_platform/engine/fbu_performance/parser.py`

- [ ] **Step 1: 添加 parse_attendance_preview 方法**

在 `parse_performance` 方法之后添加：

```python
def parse_attendance_preview(self, filepath: str, target_month: int) -> dict:
    """
    解析考勤数据并返回预览

    Args:
        filepath: 考勤日报表路径
        target_month: 目标月份

    Returns:
        预览数据 {员工明细列表, 汇总统计}
    """
    wb = self.load_excel(filepath)
    ws = wb['sheet1']

    # 读取数据行
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None:
            rows.append(row)

    # 处理考勤数据
    attendance_data = self.attendance_processor.process(rows, target_month)

    # 构建明细列表
    employee_list = []
    for emp_id, hours in attendance_data.items():
        employee_list.append({
            "employee_id": emp_id,
            "has_night_shift": hours['has_night_shift'],
            "day_shift": hours['白班'],
            "night_shift": hours['夜班'],
            "total_base_hours": hours['白班']['计薪出勤'] + hours['夜班']['计薪出勤'],
            "total_ot15": hours['白班']['OT1.5'] + hours['夜班']['OT1.5'],
            "total_ot20": hours['白班']['OT2.0'] + hours['夜班']['OT2.0'],
        })

    # 汇总统计
    total_employees = len(employee_list)
    night_shift_count = sum(1 for e in employee_list if e['has_night_shift'])
    total_base_hours = sum(e['total_base_hours'] for e in employee_list)
    total_ot15 = sum(e['total_ot15'] for e in employee_list)
    total_ot20 = sum(e['total_ot20'] for e in employee_list)

    return {
        "employees": employee_list,
        "summary": {
            "total_employees": total_employees,
            "day_shift_count": total_employees - night_shift_count,
            "night_shift_count": night_shift_count,
            "total_base_hours": round(total_base_hours, 2),
            "total_ot15": round(total_ot15, 2),
            "total_ot20": round(total_ot20, 2),
        }
    }
```

- [ ] **Step 2: 添加 parse_salary_preview 方法**

```python
def parse_salary_preview(self, filepath: str) -> dict:
    """
    解析薪资档案并返回预览

    Args:
        filepath: 薪资档案路径

    Returns:
        预览数据 {员工明细列表, 汇总统计}
    """
    wb = self.load_excel(filepath)
    ws = wb[wb.sheetnames[0]]

    # 读取数据行
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None:
            rows.append(row)

    salary_data = self.salary_processor.load(rows)

    # 构建明细列表
    employee_list = []
    for emp_id, info in salary_data.items():
        employee_list.append({
            "employee_id": emp_id,
            "hourly_rate": info.get('hourly_rate', 0),
            "ratio": info.get('ratio', 0),
        })

    # 汇总统计
    total_employees = len(employee_list)
    avg_hourly_rate = sum(e['hourly_rate'] for e in employee_list) / total_employees if total_employees > 0 else 0

    return {
        "employees": employee_list,
        "summary": {
            "total_employees": total_employees,
            "avg_hourly_rate": round(avg_hourly_rate, 2),
        }
    }
```

- [ ] **Step 3: 添加 parse_performance_preview 方法**

```python
def parse_performance_preview(self, filepath: str) -> dict:
    """
    解析绩效报表并返回预览

    Args:
        filepath: 绩效报表路径

    Returns:
        预览数据 {员工明细列表, 汇总统计}
    """
    from collections import defaultdict

    wb = self.load_excel(filepath)
    ws = wb[wb.sheetnames[0]]

    employee_list = []
    level_distribution = defaultdict(int)

    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[3] is None:  # 工号列
            continue

        emp_id = str(row[3]).strip()
        score = row[16]  # 总分
        level = row[17]  # 总等级
        coefficient = row[18]  # 绩效系数

        employee_list.append({
            "employee_id": emp_id,
            "score": float(score) if score else None,
            "level": str(level) if level else None,
            "coefficient": float(coefficient) if coefficient else None,
        })

        if level:
            level_distribution[str(level)] += 1

    # 汇总统计
    total_employees = len(employee_list)
    avg_score = sum(e['score'] for e in employee_list if e['score']) / total_employees if total_employees > 0 else 0

    return {
        "employees": employee_list,
        "summary": {
            "total_employees": total_employees,
            "avg_score": round(avg_score, 2),
            "level_distribution": dict(level_distribution),
        }
    }
```

- [ ] **Step 4: 添加 parse_all_from_step_data 方法**

在文件末尾添加：

```python
def parse_all_from_step_data(
    self,
    attendance_data: list,
    salary_data: list,
    performance_data: list,
) -> FBUPerformanceEngine:
    """
    从分步数据计算最终结果

    Args:
        attendance_data: 考勤预览数据中的employees列表
        salary_data: 薪资预览数据中的employees列表
        performance_data: 绩效预览数据中的employees列表

    Returns:
        计算完成的引擎实例
    """
    # 转换为字典格式
    attendance_dict = {}
    for emp in attendance_data:
        emp_id = emp['employee_id']
        attendance_dict[emp_id] = {
            '白班': emp['day_shift'],
            '夜班': emp['night_shift'],
            'has_night_shift': emp['has_night_shift'],
        }

    salary_dict = {}
    for emp in salary_data:
        emp_id = emp['employee_id']
        salary_dict[emp_id] = {
            'hourly_rate': emp['hourly_rate'],
            'ratio': emp['ratio'],
        }

    performance_dict = {}
    for emp in performance_data:
        emp_id = emp['employee_id']
        performance_dict[emp_id] = {
            'score': emp['score'],
            'level': emp['level'],
            'coefficient': emp['coefficient'],
        }

    # 构建员工数据
    employees = self.build_employees(attendance_dict, salary_dict, performance_dict)

    # 计算绩效奖金
    for emp in employees:
        BonusCalculator.calculate(emp)
        self.engine.add_employee(emp)

    return self.engine
```

- [ ] **Step 5: 提交**

```bash
git add bonus_platform/engine/fbu_performance/parser.py
git commit -m "feat(fbu-performance): add preview methods for step-by-step import"
```

---

## Task 3: 添加分步导入 API 端点

**Files:**
- Modify: `bonus_platform/app.py:1517-1560`

- [ ] **Step 1: 添加 import-attendance API**

在 `fbu_run_manager = FBURunManager(...)` 之后、原有 `@app.post("/api/fbu-performance/import")` 之前添加：

```python
@app.post("/api/fbu-performance/import-attendance")
async def import_fbu_attendance(
    file: UploadFile = File(...),
    calc_month: str = Body(...),
) -> dict:
    """Step 1: 导入考勤日报表"""
    # 创建运行记录
    run = fbu_run_manager.create_run(calc_month=calc_month)

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    file_path = run_dir / "attendance.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新文件名
    fbu_run_manager.update_run(run.run_id, attendance_file=file.filename)

    # 解析并预览
    try:
        target_month = int(calc_month.split("-")[1]) if "-" in calc_month else int(calc_month)
        parser = FBUPerformanceParser()
        preview = parser.parse_attendance_preview(str(file_path), target_month)

        # 保存分步数据
        fbu_run_manager.save_step_data(run.run_id, 1, preview)

        return {
            "success": True,
            "run_id": run.run_id,
            "step": 1,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run.run_id, status="failed", error=str(e))
        raise HTTPException(500, f"考勤数据解析失败: {str(e)}")
```

- [ ] **Step 2: 添加 import-salary API**

```python
@app.post("/api/fbu-performance/import-salary")
async def import_fbu_salary(
    run_id: str = Body(...),
    file: UploadFile = File(...),
) -> dict:
    """Step 2: 导入薪资档案"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    file_path = run_dir / "salary.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新文件名
    fbu_run_manager.update_run(run_id, salary_file=file.filename)

    # 解析并预览
    try:
        parser = FBUPerformanceParser()
        preview = parser.parse_salary_preview(str(file_path))

        # 保存分步数据
        fbu_run_manager.save_step_data(run_id, 2, preview)

        return {
            "success": True,
            "run_id": run_id,
            "step": 2,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"薪资数据解析失败: {str(e)}")
```

- [ ] **Step 3: 添加 import-performance API**

```python
@app.post("/api/fbu-performance/import-performance")
async def import_fbu_performance(
    run_id: str = Body(...),
    file: UploadFile = File(...),
) -> dict:
    """Step 3: 导入绩效报表"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    file_path = run_dir / "performance.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新文件名
    fbu_run_manager.update_run(run_id, performance_file=file.filename)

    # 解析并预览
    try:
        parser = FBUPerformanceParser()
        preview = parser.parse_performance_preview(str(file_path))

        # 保存分步数据
        fbu_run_manager.save_step_data(run_id, 3, preview)

        return {
            "success": True,
            "run_id": run_id,
            "step": 3,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"绩效数据解析失败: {str(e)}")
```

- [ ] **Step 4: 修改 calculate API 支持分步数据**

将原有的 `calculate_fbu_performance` 函数修改为：

```python
@app.post("/api/fbu-performance/calculate/{run_id}")
def calculate_fbu_performance(run_id: str) -> dict:
    """执行FBU绩效核算"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    try:
        fbu_run_manager.update_run(run_id, status="processing")

        parser = FBUPerformanceParser()

        # 判断是分步模式还是一次性导入模式
        if run.current_step >= 3 and run.attendance_data and run.salary_data and run.performance_data:
            # 分步模式：从已保存的分步数据计算
            engine = parser.parse_all_from_step_data(
                attendance_data=run.attendance_data.get('employees', []),
                salary_data=run.salary_data.get('employees', []),
                performance_data=run.performance_data.get('employees', []),
            )
        else:
            # 一次性导入模式：从文件计算
            run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
            target_month = int(run.calc_month.split("-")[1]) if "-" in run.calc_month else int(run.calc_month)

            engine = parser.parse_all(
                attendance_file=str(run_dir / "attendance.xlsx"),
                salary_file=str(run_dir / "salary.xlsx"),
                performance_file=str(run_dir / "performance.xlsx"),
                target_month=target_month,
            )

        # 保存结果
        employees = engine.get_all_employees()
        fbu_run_manager.save_results(run_id, employees)

        return {
            "success": True,
            "run_id": run_id,
            "total_employees": len(employees),
            "total_bonus": sum(e.performance_bonus for e in employees),
        }

    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"计算失败: {str(e)}")
```

- [ ] **Step 5: 提交**

```bash
git add bonus_platform/app.py
git commit -m "feat(fbu-performance): add step-by-step import API endpoints"
```

---

## Task 4: 重写前端为 Wizard 模式

**Files:**
- Rewrite: `bonus_platform/static/fbu-performance.html`
- Rewrite: `bonus_platform/static/fbu-performance.js`

- [ ] **Step 1: 备份原文件**

```bash
cd "/Users/zt27532/Documents/New project 2"
cp bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.html.bak
cp bonus_platform/static/fbu-performance.js bonus_platform/static/fbu-performance.js.bak
```

- [ ] **Step 2: 重写 fbu-performance.html**

使用wizard drawer模式，包含5个步骤面板。参考 `bonus_platform/static/domestic-labor.html` 的 `.wizard-drawer` 结构。

关键结构：
- `<aside class="wizard-drawer">` - 侧边栏wizard
- `<div class="wizard-steps">` - 步骤导航条
- `<div class="wz-panel" data-panel="1">` - 每个步骤的内容面板
- `<section id="previewSection">` - 数据预览区域
- `<section id="resultsSection">` - 最终结果表格

完整HTML内容参见已实现的 `fbu-performance.html` 文件。

- [ ] **Step 3: 重写 fbu-performance.js**

实现分步交互逻辑：

```javascript
// 状态管理
const state = {
  currentRunId: null,
  currentStep: 1,
  calcMonth: '2026-04',
  attendanceFile: null,
  salaryFile: null,
  performanceFile: null,
  attendancePreview: null,
  salaryPreview: null,
  performancePreview: null,
};

// 步骤导航
function goToStep(step) {
  document.querySelectorAll('.wz-step').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.wz-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.wz-step[data-step="${step}"]`).classList.add('active');
  document.querySelector(`.wz-panel[data-panel="${step}"]`).classList.add('active');
  state.currentStep = step;
  updatePreviewForStep(step);
}

// Step 1: 上传考勤
el.btnToStep2.addEventListener('click', async () => {
  const formData = new FormData();
  formData.append('file', state.attendanceFile);
  formData.append('calc_month', el.calcMonth.value);

  const response = await fetch(`${API_BASE}/import-attendance`, {
    method: 'POST',
    body: formData,
  });

  const data = await response.json();
  if (data.success) {
    state.currentRunId = data.run_id;
    state.attendancePreview = data.preview;
    renderAttendancePreview(data.preview);
    goToStep(2);
  }
});

// 类似实现 Step 2, 3, 4, 5...
```

完整JS内容参见已实现的 `fbu-performance.js` 文件。

- [ ] **Step 4: 验证CSS样式**

确认 `bonus_platform/static/styles.css` 中已有wizard相关样式：
- `.wizard-drawer`
- `.wz-step`
- `.wz-panel`
- `.upload-zone`
- `.confirm-summary`

如果缺失，从 `domestic-labor.html` 对应的styles.css中复制。

- [ ] **Step 5: 提交**

```bash
git add bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js
git commit -m "feat(fbu-performance): rewrite frontend as 5-step wizard with preview"
```

---

## Task 5: 端到端测试

**Files:**
- Test data: `/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/`

- [ ] **Step 1: 启动服务器**

```bash
cd "/Users/zt27532/Documents/New project 2"
python -m bonus_platform.app
```

- [ ] **Step 2: 测试考勤导入**

```bash
curl -s -X POST http://localhost:8000/api/fbu-performance/import-attendance \
  -F "file=@/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/考勤日报表-20260520.xlsx" \
  -F "calc_month=2026-04"
```

预期结果：
```json
{
  "success": true,
  "run_id": "xxxxxxxx",
  "step": 1,
  "preview": {
    "employees": [...],
    "summary": {
      "total_employees": 298,
      "day_shift_count": ...,
      "night_shift_count": ...,
      "total_base_hours": ...,
      "total_ot15": ...,
      "total_ot20": ...
    }
  }
}
```

- [ ] **Step 3: 测试薪资导入**

```bash
curl -s -X POST http://localhost:8000/api/fbu-performance/import-salary \
  -F "file=@/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/OEHR数据表/1779277434142薪酬档案-（含离职）.xlsx" \
  -F "run_id=<上一步返回的run_id>"
```

- [ ] **Step 4: 测试绩效导入**

```bash
curl -s -X POST http://localhost:8000/api/fbu-performance/import-performance \
  -F "file=@/Users/zt27532/Documents/FBU美洲大区激励方案/4月绩效奖金/4月绩效报表.xlsx" \
  -F "run_id=<上一步返回的run_id>"
```

- [ ] **Step 5: 测试计算**

```bash
curl -s -X POST http://localhost:8000/api/fbu-performance/calculate/<run_id>
```

预期结果：
```json
{
  "success": true,
  "run_id": "xxxxxxxx",
  "total_employees": 294,
  "total_bonus": 87695.18
}
```

- [ ] **Step 6: 测试断点续传**

1. 创建新任务，只上传考勤
2. 记录 run_id
3. 直接调用薪资导入API（模拟刷新后继续）
4. 继续绩效导入
5. 执行计算
6. 验证结果与一次性导入一致

- [ ] **Step 7: 测试浏览器UI**

1. 访问 `http://localhost:8000/fbu-performance.html`
2. 点击"新建核算任务"
3. 按步骤上传三个文件
4. 验证每步显示正确的预览表格
5. 点击"开始计算"
6. 验证结果显示正确
7. 点击"导出Excel"

- [ ] **Step 8: 提交测试通过**

```bash
git add -A
git commit -m "test(fbu-performance): verify step-by-step import with real data"
```

---

## 验证清单

| 验证项 | 预期结果 | 实际结果 |
|--------|----------|----------|
| 考勤导入返回完整明细 | 298名员工，每人有工时明细 | |
| 薪资导入返回完整明细 | 员工时薪和绩效比例列表 | |
| 绩效导入返回完整明细 | 188名员工，得分/等级/系数 | |
| 计算结果正确 | 294人，奖金$87,695.18 | |
| 断点续传 | 上传考勤→刷新→继续→结果一致 | |
| UI步骤切换 | wizard流畅切换，预览正确显示 | |
