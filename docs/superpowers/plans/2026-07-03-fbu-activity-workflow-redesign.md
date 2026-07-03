# FBU Activity Workflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the FBU Americas performance bonus page into a single activity-detail workflow with six compact steps, per-step upload entries, maintained 96-hour/fixed-base lists, plain-language handling items, and final merged results.

**Architecture:** Keep the existing `/fbu-performance.html` route and current FBU calculation endpoints. Replace the current multi-page activity workflow UI with one activity list layer and one activity detail layer controlled by `state.activityStep`; add a lightweight maintained-list API that writes the same `base_override_data` shape the calculation engine already consumes, so calculation meaning does not change.

**Tech Stack:** Python 3.x, FastAPI, openpyxl, pytest, static HTML/CSS, vanilla JavaScript, Playwright for browser verification.

## Global Constraints

- Work only in `/Users/zt27532/Documents/New project 2-fbu` on branch `codex/fbu-americas-performance-bonus`.
- Do not use `/Users/zt27532/Documents/New project 2` or any overseas-labor branch.
- Read and follow `DESIGN.md`: enterprise blue shell, controlled FBU purple accent, compact operational UI, table-first review, 4px/8px rhythm, 8px to 12px control radii, tabular numbers.
- Do not change FBU bonus formula semantics, employee IDs, white/night shift split rules, supplemental leave rules, adjustment parsing rules, or export business fields unless a test proves the existing UI cannot express the approved workflow.
- Do not introduce React, shadcn, Tailwind, or new frontend dependencies.
- Left navigation must not carry FBU workflow steps.
- Activity detail steps are exactly: `人员核对`, `考勤工时`, `薪资数据`, `绩效数据`, `核算检查`, `确认导出`.
- Upload entries belong to one step only; no centralized upload area and no duplicate upload buttons for the same material.
- `补充假勤` is required and belongs only to `考勤工时`.
- `96工时制员工` and `固定基数人员` are maintained on the page, not uploaded.
- Top-level step summary numbers use small text, not KPI-sized numerals.
- Tables only freeze `工号` and `姓名`.
- UI copy must not show these words: `诊断`, `阻断项`, `审计记录`, `人工确认项`, `口径`, `链路`, `上下文`, `规则命中`, `来源映射`, `异常记录`.
- Use plain user-facing alternatives: `需要处理`, `检查结果`, `查看说明`, `请确认`, `已自动处理`, `计算说明`.
- Special person tags appear beside names: `区长`, `96工时制`, `固定基数`, `存在调薪`, `离职发放`; they are not red warning states.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `tests/test_fbu_activity_workflow_static.py` | Static contract for approved workflow IA, wording, upload placement, compact controls, and special tags | Create |
| `tests/test_fbu_rule_list_api.py` | API contract for page-maintained 96-hour and fixed-base lists | Create |
| `bonus_platform/engine/fbu_performance/runs.py` | Store and expose global maintained rule lists beside existing roster store | Modify |
| `bonus_platform/app.py` | Add maintained-list API and per-run confirmation endpoint; reuse existing `base_override_data` | Modify |
| `bonus_platform/static/fbu-performance.html` | Replace workflow markup with activity list + activity detail shell; remove duplicate upload/modal surfaces from workflow | Modify |
| `bonus_platform/static/fbu-performance.js` | Add six-step state/rendering, per-step material rows, maintained-list editor, step-local needs, special tags, final merged result rows | Modify |
| `tools/fbu_real_e2e.py` | Stop generating/uploading 96-hour marker workbook in the normal UI path; keep calculation comparison helper usable | Modify only if its UI run path still expects rule upload |

---

## Task 1: Add Static UI Contracts Before Changing UI

**Files:**
- Create: `tests/test_fbu_activity_workflow_static.py`
- Modify: `tests/test_fbu_workbench_static.py`

**Interfaces:**
- Consumes: `bonus_platform/static/fbu-performance.html`, `bonus_platform/static/fbu-performance.js`
- Produces: failing tests that define the new activity workflow before implementation

- [ ] **Step 1: Create the new static workflow test file**

Create `tests/test_fbu_activity_workflow_static.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"


def _html() -> str:
    return FBU_HTML.read_text(encoding="utf-8")


def _js() -> str:
    return FBU_JS.read_text(encoding="utf-8")


def test_activity_detail_uses_six_plain_language_steps():
    js = _js()

    for label in ["人员核对", "考勤工时", "薪资数据", "绩效数据", "核算检查", "确认导出"]:
        assert label in js

    assert "const ACTIVITY_STEPS" in js
    assert "function setActivityStep" in js
    assert "function renderActivityStepper" in js
    assert "activity-step-summary" in js


def test_sidebar_does_not_contain_fbu_workflow_entries():
    html = _html()
    sidebar = html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]

    for forbidden in ["考勤汇总", "薪资匹配", "绩效明细", "核算结果", "异常队列", "基础数据"]:
        assert forbidden not in sidebar

    assert 'data-page="activities"' in sidebar
    assert 'data-page="workbench"' in sidebar


def test_upload_entries_are_owned_by_exactly_one_step():
    js = _js()

    assert "const STEP_MATERIALS" in js
    for key in [
        "roster",
        "attendance",
        "previousAttendance",
        "supplementalLeave",
        "salary",
        "adjustments",
        "performance",
    ]:
        assert js.count(f"materialKey: '{key}'") == 1

    for copy in [
        "上传OEHR当月考勤日报表",
        "上传OEHR上月考勤日报表",
        "上传线下sickpay与年假补充数据",
        "上传OEHR最新薪资档案（含离职）",
        "上传OEHR转正调薪流程",
        "上传OEHR当月绩效报表",
    ]:
        assert copy in js


def test_maintained_lists_replace_rule_upload_in_activity_flow():
    html = _html()
    js = _js()

    assert "workbenchUploadBaseOverrides" not in html
    assert "function renderMaintainedRuleList" in js
    assert "function confirmMaintainedRuleList" in js
    assert "96工时制员工" in js
    assert "固定基数人员" in js
    assert "确认名单" in js
    assert "管理名单" in js


def test_no_banned_words_in_workbench_user_copy():
    combined = _html() + "\n" + _js()
    user_copy_regions = [
        "ACTIVITY_STEPS",
        "STEP_MATERIALS",
        "renderActivityStepper",
        "renderStepHeader",
        "renderNeedsPanel",
        "renderFinalResultRow",
        "renderFinalCalculationDetail",
    ]

    snippets = []
    for marker in user_copy_regions:
        if marker in combined:
            snippets.append(combined.split(marker, 1)[1][:4000])
    searchable = "\n".join(snippets)

    for forbidden in ["诊断", "阻断项", "审计记录", "人工确认项", "口径", "链路", "上下文", "规则命中", "来源映射", "异常记录"]:
        assert forbidden not in searchable


def test_special_person_tags_are_rendered_near_name():
    js = _js()

    assert "function getSpecialPersonTags" in js
    assert "function renderNameWithTags" in js
    for label in ["区长", "96工时制", "固定基数", "存在调薪", "离职发放"]:
        assert label in js
    assert "person-tag" in js


def test_final_table_freezes_only_employee_id_and_name():
    html = _html()
    js = _js()

    assert ".sticky-employee-id" in html
    assert ".sticky-employee-name" in html
    assert ".sticky-bonus" not in html
    assert "sticky-bonus" not in js
```

- [ ] **Step 2: Update the older static test to stop asserting the retired one-screen card layout**

Modify `tests/test_fbu_workbench_static.py` so it delegates the workflow assertions to the new file and keeps only the hover sidebar regression:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"


def test_fbu_sidebar_expands_on_desktop_hover_and_focus():
    html = FBU_HTML.read_text(encoding="utf-8")

    desktop_sidebar = html.split("HRIS reference control language", 1)[1].split(".top-bar {", 1)[0]
    top_bar = html.split(".top-bar {", 1)[1].split("}", 1)[0]

    assert "position: fixed;" in desktop_sidebar
    assert "left: 12px;" in desktop_sidebar
    assert "width: 64px;" in desktop_sidebar
    assert "background: #ffffff;" in desktop_sidebar
    assert "transition: width 220ms cubic-bezier(0.2, 0.8, 0.2, 1)" in desktop_sidebar
    assert ".sidebar:hover," in desktop_sidebar
    assert ".sidebar:focus-within" in desktop_sidebar
    assert "width: 196px;" in desktop_sidebar
    assert ".sidebar:hover .nav-item-text" in desktop_sidebar
    assert "position: relative;" in top_bar
    assert "z-index: 40;" in top_bar
```

- [ ] **Step 3: Run the new tests and confirm they fail for the current UI**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py -q
```

Expected: failures for missing six-step workflow, duplicate workflow sidebar entries, and the old rule-table upload input still present.

- [ ] **Step 4: Commit**

```bash
git add tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py
git commit -m "test: define fbu activity workflow ui contract"
```

---

## Task 2: Add Page-Maintained Rule List API

**Files:**
- Modify: `bonus_platform/engine/fbu_performance/runs.py`
- Modify: `bonus_platform/app.py`
- Create: `tests/test_fbu_rule_list_api.py`

**Interfaces:**
- Produces: `FBURuleListStore`
- Produces: `GET /api/fbu-performance/rule-lists`
- Produces: `POST /api/fbu-performance/rule-lists`
- Produces: `POST /api/fbu-performance/runs/{run_id}/rule-lists/confirm`
- Consumes: existing `base_override_data` shape used by `parse_all_from_step_data`

- [ ] **Step 1: Write API tests for default maintained lists**

Create `tests/test_fbu_rule_list_api.py`:

```python
import json

from fastapi.testclient import TestClient

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.runs import FBURunManager, FBURuleListStore


def _client_with_tmp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_rule_list_store", FBURuleListStore(str(tmp_path)))
    return TestClient(app_module.app)


def test_rule_lists_return_seeded_96_hour_and_fixed_base_lists(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    response = client.get("/api/fbu-performance/rule-lists")

    assert response.status_code == 200
    payload = response.json()
    assert {row["employee_id"] for row in payload["work_hour_employees"]} == {
        "zt12979",
        "zt12988",
        "zt14260",
        "zt17850",
    }
    assert payload["fixed_base_employees"][0]["employee_id"] == "zt15638"
    assert payload["fixed_base_employees"][0]["fixed_performance_base"] == 3000


def test_rule_lists_can_be_saved_without_uploading_workbook(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    response = client.post(
        "/api/fbu-performance/rule-lists",
        json={
            "work_hour_employees": [
                {"employee_id": "zt12988", "name": "陈海冰", "active": True},
            ],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "万其鑫", "fixed_performance_base": 3000, "active": True},
            ],
        },
    )

    assert response.status_code == 200
    saved = json.loads((tmp_path / "_settings" / "rule_lists.json").read_text(encoding="utf-8"))
    assert saved["work_hour_employees"][0]["employee_id"] == "zt12988"
    assert saved["fixed_base_employees"][0]["fixed_performance_base"] == 3000


def test_confirm_rule_lists_writes_base_override_data_to_run(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]

    response = client.post(
        f"/api/fbu-performance/runs/{run_id}/rule-lists/confirm",
        json={
            "work_hour_employees": [
                {"employee_id": "zt12988", "name": "陈海冰", "active": True},
            ],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "万其鑫", "fixed_performance_base": 3000, "active": True},
            ],
        },
    )

    assert response.status_code == 200
    detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    rows = detail["base_override_data"]["employees"]
    by_id = {row["employee_id"]: row for row in rows}
    assert by_id["zt12988"]["rule_type"] == "96工时制"
    assert by_id["zt12988"]["fixed_performance_base"] is None
    assert by_id["zt15638"]["rule_type"] == "线下固定基数覆盖"
    assert by_id["zt15638"]["fixed_performance_base"] == 3000
    assert detail["base_override_file"] == "页面维护"
```

- [ ] **Step 2: Implement `FBURuleListStore`**

Add this class after `FBURosterStore` in `bonus_platform/engine/fbu_performance/runs.py`:

```python
DEFAULT_WORK_HOUR_EMPLOYEES = [
    {"employee_id": "zt12979", "name": "赵婉妍", "active": True},
    {"employee_id": "zt12988", "name": "陈海冰", "active": True},
    {"employee_id": "zt14260", "name": "陈炜", "active": True},
    {"employee_id": "zt17850", "name": "韩勇", "active": True},
]

DEFAULT_FIXED_BASE_EMPLOYEES = [
    {
        "employee_id": "zt15638",
        "name": "万其鑫",
        "fixed_performance_base": 3000,
        "active": True,
    },
]


class FBURuleListStore:
    """Stores stable FBU 96-hour and fixed-base lists outside monthly uploads."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.settings_dir = self.data_dir / "_settings"
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.rule_lists_file = self.settings_dir / "rule_lists.json"

    def _default_payload(self) -> dict:
        return {
            "work_hour_employees": list(DEFAULT_WORK_HOUR_EMPLOYEES),
            "fixed_base_employees": list(DEFAULT_FIXED_BASE_EMPLOYEES),
        }

    def get(self) -> dict:
        if not self.rule_lists_file.exists():
            return self._default_payload()
        with open(self.rule_lists_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        defaults = self._default_payload()
        return {
            "work_hour_employees": payload.get("work_hour_employees", defaults["work_hour_employees"]),
            "fixed_base_employees": payload.get("fixed_base_employees", defaults["fixed_base_employees"]),
        }

    def save(self, payload: dict) -> dict:
        normalized = {
            "work_hour_employees": self._normalize_work_hour_rows(payload.get("work_hour_employees", [])),
            "fixed_base_employees": self._normalize_fixed_base_rows(payload.get("fixed_base_employees", [])),
        }
        with open(self.rule_lists_file, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        return normalized

    def _normalize_work_hour_rows(self, rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            employee_id = str(row.get("employee_id") or "").strip()
            if not employee_id:
                continue
            result.append({
                "employee_id": employee_id,
                "name": str(row.get("name") or "").strip(),
                "active": bool(row.get("active", True)),
            })
        return result

    def _normalize_fixed_base_rows(self, rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            employee_id = str(row.get("employee_id") or "").strip()
            if not employee_id:
                continue
            result.append({
                "employee_id": employee_id,
                "name": str(row.get("name") or "").strip(),
                "fixed_performance_base": float(row.get("fixed_performance_base") or 0),
                "active": bool(row.get("active", True)),
            })
        return result
```

- [ ] **Step 3: Wire store and preview builder in `bonus_platform/app.py`**

Add near existing FBU stores:

```python
from .engine.fbu_performance.runs import FBURuleListStore

fbu_rule_list_store = FBURuleListStore(str(FBU_PERFORMANCE_RUNS_DIR))
```

Add helper functions near `_fbu_run_diagnostics`:

```python
def _build_base_override_data_from_rule_lists(calc_month: str, payload: dict) -> dict:
    employees = []
    for row in payload.get("work_hour_employees", []):
        if not row.get("active", True):
            continue
        employees.append({
            "employee_id": str(row.get("employee_id") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "rule_type": "96工时制",
            "fixed_performance_base": None,
            "month": calc_month,
            "status": "启用",
            "note": "页面维护",
            "calculation_path": "96工时制自动基数路径",
        })
    for row in payload.get("fixed_base_employees", []):
        if not row.get("active", True):
            continue
        employees.append({
            "employee_id": str(row.get("employee_id") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "rule_type": "线下固定基数覆盖",
            "fixed_performance_base": float(row.get("fixed_performance_base") or 0),
            "month": calc_month,
            "status": "启用",
            "note": "页面维护",
            "calculation_path": "线下固定基数覆盖路径",
        })
    employees = [row for row in employees if row["employee_id"]]
    fixed_base_total = sum(float(row.get("fixed_performance_base") or 0) for row in employees)
    return {
        "employees": employees,
        "summary": {
            "total_rows": len(employees),
            "active_count": len(employees),
            "work_hour_rule_count": sum(1 for row in employees if row["rule_type"] == "96工时制"),
            "fixed_base_count": sum(1 for row in employees if row["rule_type"] == "线下固定基数覆盖"),
            "active_fixed_base": fixed_base_total,
        },
    }
```

- [ ] **Step 4: Add API routes**

Add below `upload_fbu_base_roster`:

```python
@app.get("/api/fbu-performance/rule-lists")
def get_fbu_rule_lists() -> dict:
    return fbu_rule_list_store.get()


@app.post("/api/fbu-performance/rule-lists")
def save_fbu_rule_lists(body: dict = Body(...)) -> dict:
    return fbu_rule_list_store.save(body)


@app.post("/api/fbu-performance/runs/{run_id}/rule-lists/confirm")
def confirm_fbu_run_rule_lists(run_id: str, body: dict = Body(...)) -> dict:
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    saved = fbu_rule_list_store.save(body)
    preview = _build_base_override_data_from_rule_lists(run.calc_month, saved)
    fbu_run_manager.update_run(
        run_id,
        base_override_file="页面维护",
        base_override_data=preview,
    )
    return {"success": True, "run_id": run_id, "preview": preview, "rule_lists": saved}
```

- [ ] **Step 5: Run API tests**

Run:

```bash
python3 -m pytest tests/test_fbu_rule_list_api.py tests/test_fbu_base_overrides.py -q
```

Expected: all tests pass after implementation.

- [ ] **Step 6: Commit**

```bash
git add bonus_platform/engine/fbu_performance/runs.py bonus_platform/app.py tests/test_fbu_rule_list_api.py
git commit -m "feat: maintain fbu rule lists on page"
```

---

## Task 3: Replace Activity Detail Shell and Sidebar Flow

**Files:**
- Modify: `bonus_platform/static/fbu-performance.html`
- Modify: `bonus_platform/static/fbu-performance.js`

**Interfaces:**
- Consumes: existing `state.currentActivity`, `enterActivity(runId, options)`, `openWorkbenchUpload(type)`, `executeCalculate()`, `exportData(type)`
- Produces: `state.activityStep`
- Produces: `ACTIVITY_STEPS`
- Produces: `setActivityStep(stepKey)`
- Produces: `renderActivityDetail(activity)`

- [ ] **Step 1: Change JS state and step constants**

At the top of `bonus_platform/static/fbu-performance.js`, add `activityStep` and replace workflow page assumptions:

```javascript
const state = {
  currentPage: 'workbench',
  activityStep: 'people',
  currentActivity: null,
  activities: [],
  attendanceData: null,
  salaryData: null,
  performanceData: null,
  adjustmentData: null,
  supplementalLeaveData: null,
  baseOverrideData: null,
  ruleLists: null,
  diagnosticsData: null,
  resultsData: null,
  baseRoster: null,
  lastImportResult: null,
  foundationRunDetails: {},
  foundationLoadingRunId: '',
  activityListLoadingRunIds: new Set(),
  workbenchSelectedResult: '',
  workbenchResultFilter: 'all',
  workbenchPreviousAttendanceFile: null,
  tableFilters: {
    attendance: {},
    salary: {},
    performance: {},
    supplementalLeave: {},
    baseOverrides: {},
    results: {},
    exceptions: {},
  },
  tablePagination: {
    attendance: { page: 1, pageSize: 50 },
    salary: { page: 1, pageSize: 50 },
    performance: { page: 1, pageSize: 50 },
    supplementalLeave: { page: 1, pageSize: 50 },
    baseOverrides: { page: 1, pageSize: 50 },
    results: { page: 1, pageSize: 50 },
    exceptions: { page: 1, pageSize: 50 },
  },
};

const ACTIVITY_STEPS = [
  { key: 'people', label: '人员核对' },
  { key: 'attendance', label: '考勤工时' },
  { key: 'salary', label: '薪资数据' },
  { key: 'performance', label: '绩效数据' },
  { key: 'check', label: '核算检查' },
  { key: 'export', label: '确认导出' },
];
```

- [ ] **Step 2: Simplify sidebar HTML to platform-level entries**

In `bonus_platform/static/fbu-performance.html`, replace `<nav class="sidebar-nav">...</nav>` with:

```html
<nav class="sidebar-nav">
  <div class="nav-section">
    <div class="nav-section-title">平台模块</div>
    <a class="nav-item active" href="#workbench" data-page="workbench" aria-current="page">
      <span class="nav-item-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 4h14v12H3V4z" stroke="currentColor" stroke-width="1.5"/><path d="M6 8h3M6 12h3M12 8h2M12 12h2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </span>
      <span class="nav-item-text">FBU核算</span>
    </a>
    <a class="nav-item" href="#activities" data-page="activities">
      <span class="nav-item-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 3h14a2 2 0 012 2v10a2 2 0 01-2 2H3a2 2 0 01-2-2V5a2 2 0 012-2z" stroke="currentColor" stroke-width="1.5"/><path d="M7 7h6M7 10h6M7 13h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </span>
      <span class="nav-item-text">活动列表</span>
    </a>
  </div>
</nav>
```

- [ ] **Step 3: Replace page shells with only activity detail and activity list**

Keep `pageWorkbench` and `pageActivities`. Remove the separate visible shells for `pageFoundation`, `pageExceptions`, `pageAttendance`, `pageSalary`, `pagePerformance`, and `pageResults`. Replace the workbench shell content with:

```html
<div class="page-content" id="pageWorkbench">
  <div class="fbu-activity-detail" id="workbenchContent">
    <div class="workbench-empty">
      <h2>正在读取活动</h2>
      <p>读取最近一次月度活动。</p>
    </div>
  </div>
  <div class="workbench-file-inputs" aria-hidden="true">
    <input id="workbenchUploadRoster" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadAttendance" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadPreviousAttendance" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadSalary" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadPerformance" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadAdjustments" type="file" accept=".xlsx,.xls" />
    <input id="workbenchUploadSupplementalLeave" type="file" accept=".xlsx,.xls" />
  </div>
</div>
```

- [ ] **Step 4: Update `el.pages` and `navigateTo`**

In the `el` object keep only activity layers:

```javascript
pages: {
  workbench: document.getElementById('pageWorkbench'),
  activities: document.getElementById('pageActivities'),
},
```

Replace `navigateTo(page)` title mapping with:

```javascript
const titles = {
  workbench: { title: 'FBU美洲绩效核算', subtitle: state.currentActivity?.calc_month || '' },
  activities: { title: 'FBU美洲绩效核算', subtitle: '活动列表' },
};
```

Remove calls that render retired page shells from `navigateTo`; it should only call `renderWorkbench()` or `loadActivities()`.

- [ ] **Step 5: Add step switching**

Add below navigation helpers:

```javascript
function setActivityStep(stepKey) {
  if (!ACTIVITY_STEPS.some(step => step.key === stepKey)) return;
  state.activityStep = stepKey;
  renderWorkbench();
}

function getStepIndex(stepKey) {
  return ACTIVITY_STEPS.findIndex(step => step.key === stepKey);
}
```

- [ ] **Step 6: Run static tests**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py -q
```

Expected: sidebar and shell tests pass; content-specific tests can still fail until later tasks add render functions.

- [ ] **Step 7: Commit**

```bash
git add bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js
git commit -m "feat: simplify fbu activity shell"
```

---

## Task 4: Add Per-Step Materials and Maintained Lists

**Files:**
- Modify: `bonus_platform/static/fbu-performance.js`
- Modify: `bonus_platform/static/fbu-performance.html`

**Interfaces:**
- Consumes: `GET /api/fbu-performance/rule-lists`
- Consumes: `POST /api/fbu-performance/runs/{run_id}/rule-lists/confirm`
- Produces: `STEP_MATERIALS`
- Produces: `renderMaterialRow(material, activity)`
- Produces: `renderMaintainedRuleList(kind, activity)`
- Produces: `confirmMaintainedRuleList(kind)`

- [ ] **Step 1: Add material definitions**

Add after `ACTIVITY_STEPS`:

```javascript
const STEP_MATERIALS = {
  people: [
    { materialKey: 'roster', label: '花名册', tag: '必传', hint: '上传人员基础资料', uploadType: 'roster', fileField: 'roster_file', required: true },
  ],
  attendance: [
    { materialKey: 'attendance', label: '考勤日报', tag: '必传', hint: '上传OEHR当月考勤日报表', uploadType: 'attendance', fileField: 'attendance_file', required: true },
    { materialKey: 'previousAttendance', label: '上月考勤', tag: '96工时制员工', hint: '上传OEHR上月考勤日报表', uploadType: 'previousAttendance', fileField: 'previous_attendance_file', required: false, conditional: 'needsPreviousAttendance' },
    { materialKey: 'supplementalLeave', label: '补充假勤', tag: '必传', hint: '上传线下sickpay与年假补充数据', uploadType: 'supplementalLeave', fileField: 'supplemental_leave_file', required: true },
  ],
  salary: [
    { materialKey: 'salary', label: '薪资档案', tag: '必传', hint: '上传OEHR最新薪资档案（含离职）', uploadType: 'salary', fileField: 'salary_file', required: true },
    { materialKey: 'adjustments', label: '当月转正/调薪表', tag: '按需', hint: '上传OEHR转正调薪流程', uploadType: 'adjustments', fileField: 'adjustment_file', required: false },
  ],
  performance: [
    { materialKey: 'performance', label: '绩效报表', tag: '必传', hint: '上传OEHR当月绩效报表', uploadType: 'performance', fileField: 'performance_file', required: true },
  ],
  check: [],
  export: [],
};
```

- [ ] **Step 2: Add compact material renderer**

Add:

```javascript
function needsPreviousAttendance(activity) {
  const context = activity?.attendance_data?.summary?.attendance_context || {};
  return Boolean(context.required || activity?.previous_attendance_file || state.workbenchPreviousAttendanceFile);
}

function getMaterialStatus(material, activity) {
  if (material.conditional === 'needsPreviousAttendance' && !needsPreviousAttendance(activity)) {
    return { visible: false };
  }
  const fileName = activity?.[material.fileField] || '';
  if (fileName) {
    return { visible: true, tone: 'success', text: '已上传', fileName };
  }
  if (material.materialKey === 'previousAttendance' && state.workbenchPreviousAttendanceFile) {
    return { visible: true, tone: 'warning', text: '已选择', fileName: state.workbenchPreviousAttendanceFile.name };
  }
  return { visible: true, tone: material.required ? 'warning' : 'neutral', text: material.required ? '未上传' : '按需', fileName: '' };
}

function renderMaterialRow(material, activity) {
  const status = getMaterialStatus(material, activity);
  if (!status.visible) return '';
  const actionText = status.fileName ? '重新上传' : '上传';
  return `
    <div class="material-row ${escapeHtml(status.tone)}">
      <div class="material-marker"></div>
      <div class="material-main">
        <div class="material-title">
          <strong>${escapeHtml(material.label)}</strong>
          <span class="mini-tag">${escapeHtml(material.tag)}</span>
          <span class="status-badge ${escapeHtml(status.tone)}">${escapeHtml(status.text)}</span>
        </div>
        <div class="material-hint">${escapeHtml(material.hint)}</div>
      </div>
      <div class="material-file">${escapeHtml(status.fileName || '-')}</div>
      <button class="btn btn-secondary btn-sm" type="button" onclick="openWorkbenchUpload(${formatJsArg(material.uploadType)})">${actionText}</button>
    </div>
  `;
}

function renderStepMaterials(stepKey, activity) {
  const rows = STEP_MATERIALS[stepKey] || [];
  if (!rows.length) return '';
  return `
    <section class="step-section material-list">
      ${rows.map(row => renderMaterialRow(row, activity)).join('')}
    </section>
  `;
}
```

- [ ] **Step 3: Load rule lists**

Add:

```javascript
async function loadRuleLists() {
  if (state.ruleLists) return state.ruleLists;
  const data = await apiJson(`${API_BASE}/rule-lists`);
  state.ruleLists = data;
  return data;
}
```

Call `loadRuleLists()` after activities load when `state.currentPage === 'workbench'`, and before rendering maintained list panels:

```javascript
if (state.currentPage === 'workbench') {
  await loadRuleLists();
}
```

- [ ] **Step 4: Add maintained-list rendering**

Add:

```javascript
function renderMaintainedRuleList(kind, activity) {
  const lists = state.ruleLists || {};
  const isWorkHour = kind === 'workHour';
  const rows = isWorkHour ? (lists.work_hour_employees || []) : (lists.fixed_base_employees || []);
  const title = isWorkHour ? '96工时制员工' : '固定基数人员';
  const confirmed = isWorkHour
    ? (activity?.base_override_data?.employees || []).some(row => row.rule_type === '96工时制')
    : (activity?.base_override_data?.employees || []).some(row => row.rule_type === '线下固定基数覆盖');
  return `
    <section class="step-section maintained-list">
      <div class="section-head compact">
        <div>
          <h3>${title}</h3>
          <p>${isWorkHour ? '本月默认沿用已确认的4名员工。' : '本月默认沿用已确认名单。'}</p>
        </div>
        <div class="section-actions">
          <span class="status-badge ${confirmed ? 'success' : 'warning'}">${confirmed ? '已确认' : '未确认'}</span>
          <button class="btn btn-secondary btn-sm" type="button" onclick="toggleMaintainedRuleEditor(${formatJsArg(kind)})">管理名单</button>
          <button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(${formatJsArg(kind)})">确认名单</button>
        </div>
      </div>
      <div class="compact-list-table">
        <table class="data-table">
          <thead><tr><th class="sticky-employee-id">工号</th><th class="sticky-employee-name">姓名</th>${isWorkHour ? '' : '<th>固定基数</th>'}<th>状态</th></tr></thead>
          <tbody>
            ${rows.map(row => `
              <tr>
                <td class="sticky-employee-id">${escapeHtml(row.employee_id)}</td>
                <td class="sticky-employee-name">${escapeHtml(row.name || '-')}</td>
                ${isWorkHour ? '' : `<td class="amount-cell">${formatCurrency(row.fixed_performance_base)}</td>`}
                <td>${row.active === false ? '停用' : '启用'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
```

- [ ] **Step 5: Add confirm action**

Add:

```javascript
async function confirmMaintainedRuleList(kind) {
  if (!state.currentActivity?.run_id) return;
  if (!state.ruleLists) await loadRuleLists();
  const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/rule-lists/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.ruleLists),
  });
  state.baseOverrideData = data.preview;
  state.currentActivity.base_override_file = '页面维护';
  state.currentActivity.base_override_data = data.preview;
  renderWorkbench();
  showNotification(kind === 'workHour' ? '96工时制名单已确认' : '固定基数名单已确认', 'success');
}

function toggleMaintainedRuleEditor(kind) {
  const panel = document.querySelector(`[data-maintained-editor="${kind}"]`);
  if (panel) panel.hidden = !panel.hidden;
}
```

- [ ] **Step 6: Remove base-overrides upload from UI path**

Remove `workbenchUploadBaseOverrides` from HTML and remove `baseOverrides` from `getWorkbenchUploadInput`. Keep the old `/api/fbu-performance/import-base-overrides` endpoint for compatibility and tests.

- [ ] **Step 7: Run tests**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_rule_list_api.py -q
```

Expected: material ownership and maintained-list tests pass.

- [ ] **Step 8: Commit**

```bash
git add bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js
git commit -m "feat: place fbu materials inside workflow steps"
```

---

## Task 5: Render Six Step Work Areas and Plain-Language Needs

**Files:**
- Modify: `bonus_platform/static/fbu-performance.js`
- Modify: `bonus_platform/static/fbu-performance.html`

**Interfaces:**
- Consumes: `STEP_MATERIALS`, `renderStepMaterials`, `renderMaintainedRuleList`
- Produces: `renderActivityStepper(activity)`
- Produces: `renderStepHeader(step, activity)`
- Produces: `buildNeedsForStep(stepKey, activity)`
- Produces: `renderNeedsPanel(stepKey, activity)`
- Produces: `renderStepContent(activity)`

- [ ] **Step 1: Add step status and summary helpers**

Add:

```javascript
function getStepStatus(stepKey, activity) {
  const needs = buildNeedsForStep(stepKey, activity);
  if (needs.length) return '需要处理';
  if (stepKey === 'people') return activity?.roster_file ? '已完成' : '未完成';
  if (stepKey === 'attendance') return activity?.attendance_file && activity?.supplemental_leave_file ? '已完成' : '未完成';
  if (stepKey === 'salary') return activity?.salary_file ? '已完成' : '未完成';
  if (stepKey === 'performance') return activity?.performance_file || activity?.performance_data?.employees?.length ? '已完成' : '未完成';
  if (stepKey === 'check') return activity?.results?.length ? '已完成' : '未开始';
  if (stepKey === 'export') return activity?.results?.length ? '已完成' : '未开始';
  return '未开始';
}

function getStepSummary(stepKey, activity) {
  if (stepKey === 'people') return `${toNumber(activity?.attendance_data?.summary?.roster_matched)}已匹配`;
  if (stepKey === 'attendance') return `${formatHours(activity?.attendance_data?.summary?.total_base_hours)}工时`;
  if (stepKey === 'salary') return `${toNumber(activity?.salary_data?.summary?.valid_hourly_count)}有效时薪`;
  if (stepKey === 'performance') return `${toNumber(activity?.performance_data?.summary?.total_employees)}人`;
  if (stepKey === 'check') return `${buildNeedsForStep(stepKey, activity).length}项`;
  if (stepKey === 'export') return `${getWorkbenchResults(activity).length}人`;
  return '-';
}
```

- [ ] **Step 2: Add the stepper renderer**

Add:

```javascript
function renderActivityStepper(activity) {
  return `
    <div class="activity-stepper" role="tablist" aria-label="核算步骤">
      ${ACTIVITY_STEPS.map((step, index) => {
        const active = state.activityStep === step.key;
        const status = getStepStatus(step.key, activity);
        return `
          <button class="activity-step ${active ? 'active' : ''}" type="button" role="tab" aria-selected="${active}" onclick="setActivityStep(${formatJsArg(step.key)})">
            <span class="activity-step-index">${index + 1}</span>
            <span class="activity-step-label">${escapeHtml(step.label)}</span>
            <span class="activity-step-summary">${escapeHtml(getStepSummary(step.key, activity))}</span>
            <span class="activity-step-status ${status === '需要处理' ? 'warning' : status === '已完成' ? 'success' : ''}">${escapeHtml(status)}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}
```

- [ ] **Step 3: Build step-local need lists**

Add:

```javascript
function buildNeedsForStep(stepKey, activity) {
  const needs = [];
  const push = (id, text, action = '') => needs.push({ id, text, action });
  if (!activity) return needs;

  if (stepKey === 'people' && !activity.roster_file) {
    push('roster', '请上传花名册', `<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('roster')">上传</button>`);
  }
  if (stepKey === 'attendance') {
    if (!activity.attendance_file) push('attendance', '请上传考勤日报', `<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('attendance')">上传</button>`);
    if (!activity.supplemental_leave_file) push('supplementalLeave', '请上传补充假勤', `<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('supplementalLeave')">上传</button>`);
    if (!activity.base_override_data?.employees?.some(row => row.rule_type === '96工时制')) push('workHourList', '请确认96工时制员工名单', `<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList('workHour')">确认名单</button>`);
    getSupplementalSuggestionRows(getWorkbenchSupplementalRows(activity)).slice(0, 5).forEach(row => {
      push(
        `leave-${row.row_id}`,
        `${row.employee_id} ${row.name || ''} 补充假勤请确认`,
        `<button class="btn btn-primary btn-sm" type="button" onclick="applyWorkbenchSupplementalSuggestion(${formatJsArg(row.row_id)}, ${getSupplementalSuggestedHours(row)})">计入建议小时</button>`
      );
    });
  }
  if (stepKey === 'salary') {
    if (!activity.salary_file) push('salary', '请上传薪资档案', `<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('salary')">上传</button>`);
    if (!activity.base_override_data?.employees?.some(row => row.rule_type === '线下固定基数覆盖')) push('fixedBaseList', '请确认固定基数人员名单', `<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList('fixedBase')">确认名单</button>`);
  }
  if (stepKey === 'performance' && !activity.performance_file && !activity.performance_data?.employees?.length) {
    push('performance', '请上传绩效报表或补充离职人员绩效', `<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('performance')">上传</button>`);
  }
  if (stepKey === 'check') {
    ['people', 'attendance', 'salary', 'performance'].forEach(key => {
      buildNeedsForStep(key, activity).forEach(item => needs.push(item));
    });
  }
  return needs;
}

function renderNeedsPanel(stepKey, activity) {
  const needs = buildNeedsForStep(stepKey, activity);
  if (!needs.length) {
    return `<section class="step-section needs-panel complete">本步骤已完成</section>`;
  }
  return `
    <section class="step-section needs-panel">
      <div class="section-head compact"><h3>需要处理</h3></div>
      <div class="needs-list">
        ${needs.map(item => `
          <div class="need-row">
            <span>${escapeHtml(item.text)}</span>
            <span class="need-actions">${item.action}</span>
          </div>
        `).join('')}
      </div>
    </section>
  `;
}
```

- [ ] **Step 4: Add concise step help**

Add:

```javascript
const STEP_HELP = {
  people: ['花名册用于匹配姓名、部门和岗位。'],
  attendance: ['普通病假、年假按申请时间计入本月。', '离职年假默认不计入。', '96工时制员工按本月和必要的上月考勤计算。'],
  salary: ['当月转正/调薪按生效日期拆分。', '未发生转正/调薪的员工按薪资档案计算。'],
  performance: ['有绩效报表的员工按报表得分计算。', '离职员工可在本页补充绩效得分。'],
  check: ['只展示必须处理后才能继续的问题。'],
  export: ['最终结果按员工合并展示，拆分明细在行内展开。'],
};

function renderStepHelp(stepKey) {
  const rows = STEP_HELP[stepKey] || [];
  return `
    <details class="step-help">
      <summary>查看说明</summary>
      <ul>${rows.map(row => `<li>${escapeHtml(row)}</li>`).join('')}</ul>
    </details>
  `;
}
```

- [ ] **Step 5: Render per-step content**

Add:

```javascript
function renderStepContent(activity) {
  const stepKey = state.activityStep;
  if (stepKey === 'people') return renderPeopleStep(activity);
  if (stepKey === 'attendance') return renderAttendanceStep(activity);
  if (stepKey === 'salary') return renderSalaryStep(activity);
  if (stepKey === 'performance') return renderPerformanceStep(activity);
  if (stepKey === 'check') return renderCheckStep(activity);
  if (stepKey === 'export') return renderExportStep(activity);
  return '';
}
```

Then add minimal step functions that combine materials, needs, and existing tables:

```javascript
function renderPeopleStep(activity) {
  return `${renderStepMaterials('people', activity)}${renderNeedsPanel('people', activity)}${renderPeopleTable(activity)}`;
}

function renderAttendanceStep(activity) {
  return `${renderStepMaterials('attendance', activity)}${renderMaintainedRuleList('workHour', activity)}${renderNeedsPanel('attendance', activity)}${renderAttendanceSummaryTable(activity)}`;
}

function renderSalaryStep(activity) {
  return `${renderStepMaterials('salary', activity)}${renderMaintainedRuleList('fixedBase', activity)}${renderNeedsPanel('salary', activity)}${renderSalarySummaryTable(activity)}`;
}

function renderPerformanceStep(activity) {
  return `${renderStepMaterials('performance', activity)}${renderPerformanceInlineSupplement(activity)}${renderNeedsPanel('performance', activity)}${renderPerformanceSummaryTable(activity)}`;
}

function renderCheckStep(activity) {
  return `${renderNeedsPanel('check', activity)}${renderCheckPreview(activity)}`;
}

function renderExportStep(activity) {
  return `${renderFinalResults(activity)}`;
}
```

- [ ] **Step 6: Replace `renderWorkbench` body**

Replace the old card grid renderer with:

```javascript
function renderWorkbench() {
  if (!el.workbenchContent) return;
  const activity = getWorkbenchActivity();
  if (!activity) {
    el.workbenchContent.innerHTML = `
      <div class="workbench-empty">
        <h2>暂无月度活动</h2>
        <p>先创建月度活动。</p>
        <button class="btn btn-primary" type="button" onclick="document.getElementById('btnNewActivity')?.click()">新建活动</button>
      </div>
    `;
    return;
  }

  el.workbenchContent.innerHTML = `
    <section class="activity-titlebar">
      <div>
        <button class="link-button" type="button" onclick="navigateTo('activities')">返回活动列表</button>
        <h2>${escapeHtml(activity.calc_month || '-')} FBU美洲绩效核算</h2>
        <span class="activity-id">活动 ${escapeHtml(activity.run_id || '-')}</span>
      </div>
      <div class="activity-title-actions">
        ${state.activityStep === 'check' ? '<button class="btn btn-primary btn-sm" type="button" onclick="executeCalculate()">开始核算</button>' : ''}
        ${state.activityStep === 'export' ? '<button class="btn btn-primary btn-sm" type="button" onclick="exportData(\\'results\\')">导出结果</button>' : ''}
      </div>
    </section>
    ${renderActivityStepper(activity)}
    <section class="activity-step-body">
      <div class="step-topline">
        <h3>${escapeHtml(ACTIVITY_STEPS.find(step => step.key === state.activityStep)?.label || '')}</h3>
        ${renderStepHelp(state.activityStep)}
      </div>
      ${renderStepContent(activity)}
    </section>
  `;
}
```

- [ ] **Step 7: Run checks**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py -q
node --check bonus_platform/static/fbu-performance.js
```

Expected: static workflow tests pass and JavaScript syntax passes.

- [ ] **Step 8: Commit**

```bash
git add bonus_platform/static/fbu-performance.js bonus_platform/static/fbu-performance.html
git commit -m "feat: render fbu six-step activity workflow"
```

---

## Task 6: Add Tables, Name Tags, and Final Row Expansion

**Files:**
- Modify: `bonus_platform/static/fbu-performance.js`
- Modify: `bonus_platform/static/fbu-performance.html`

**Interfaces:**
- Consumes: activity data fields from existing API
- Produces: `getSpecialPersonTags(row, activity)`
- Produces: `renderNameWithTags(row, activity)`
- Produces: `renderFinalResultRow(result, activity)`
- Produces: `renderFinalCalculationDetail(result)`

- [ ] **Step 1: Add special tag helpers**

Add:

```javascript
function sourceEmployeeId(row) {
  return String(row?.source_employee_id || row?.employee_id || '').replace(/-1$/, '');
}

function getSpecialPersonTags(row, activity = getWorkbenchActivity()) {
  const tags = [];
  const employeeId = String(row?.employee_id || '');
  const sourceId = sourceEmployeeId(row);
  const baseRows = activity?.base_override_data?.employees || [];
  const adjustmentRows = activity?.adjustment_data?.employees || [];
  const adjustmentEvents = activity?.adjustment_data?.events || [];

  if (row?.job_type === 'district_manager') tags.push('区长');
  if (baseRows.some(item => sourceEmployeeId(item) === sourceId && item.rule_type === '96工时制')) tags.push('96工时制');
  if (baseRows.some(item => sourceEmployeeId(item) === sourceId && item.rule_type === '线下固定基数覆盖')) tags.push('固定基数');
  if (adjustmentRows.some(item => sourceEmployeeId(item) === sourceId) || adjustmentEvents.some(item => sourceEmployeeId(item) === sourceId)) tags.push('存在调薪');
  if (row?.personnel_status === '离职' || row?.resignation_date) tags.push('离职发放');

  return [...new Set(tags)].slice(0, 4);
}

function renderNameWithTags(row, activity = getWorkbenchActivity()) {
  const tags = getSpecialPersonTags(row, activity);
  const visible = tags.slice(0, 3);
  const extra = tags.length - visible.length;
  return `
    <span class="name-with-tags">
      <span>${escapeHtml(row?.name || '-')}</span>
      ${visible.map(tag => `<span class="person-tag">${escapeHtml(tag)}</span>`).join('')}
      ${extra > 0 ? `<span class="person-tag">+${extra}</span>` : ''}
    </span>
  `;
}
```

- [ ] **Step 2: Add compact table renderers for steps 1-4**

Add simple table functions that reuse data already in activity payload:

```javascript
function renderPeopleTable(activity) {
  const rows = activity?.attendance_data?.employees || activity?.salary_data?.employees || [];
  return renderCompactEmployeeTable('人员表', rows, ['部门', '岗位', '状态'], row => [
    row.department || row.area || '-',
    formatResultJobType(row.job_type),
    row.personnel_status || '参与',
  ], activity);
}

function renderAttendanceSummaryTable(activity) {
  const rows = activity?.attendance_data?.employees || [];
  return renderCompactEmployeeTable('工时表', rows, ['普通工时', '计入病假/年假', '96工时制'], row => [
    formatHours(toNumber(row.base_hours || row.total_base_hours)),
    formatHours(toNumber(row.sick_hours) + toNumber(row.annual_hours) + toNumber(row.sick_settlement_hours)),
    getSpecialPersonTags(row, activity).includes('96工时制') ? '是' : '-',
  ], activity);
}

function renderSalarySummaryTable(activity) {
  const rows = activity?.salary_data?.employees || [];
  return renderCompactEmployeeTable('薪资表', rows, ['时薪', '绩效比例', '固定基数'], row => [
    formatCurrency(row.hourly_rate),
    formatPercent(row.ratio),
    toNumber(row.fixed_performance_base) ? formatCurrency(row.fixed_performance_base) : '-',
  ], activity);
}

function renderPerformanceSummaryTable(activity) {
  const rows = getPerformanceReviewRows(activity?.performance_data?.employees || []);
  return renderCompactEmployeeTable('绩效表', rows, ['得分', '等级', '系数'], row => [
    formatScore(row.score),
    row.level || '-',
    formatCoefficient(row.coefficient),
  ], activity);
}

function renderCompactEmployeeTable(title, rows, headers, cellsForRow, activity) {
  return `
    <section class="step-section table-section">
      <div class="section-head compact"><h3>${escapeHtml(title)}</h3></div>
      <div class="data-table-container">
        <table class="data-table activity-table">
          <thead>
            <tr><th class="sticky-employee-id">工号</th><th class="sticky-employee-name">姓名</th>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr>
          </thead>
          <tbody>
            ${rows.length ? rows.slice(0, 80).map(row => `
              <tr>
                <td class="sticky-employee-id">${escapeHtml(row.employee_id || '-')}</td>
                <td class="sticky-employee-name">${renderNameWithTags(row, activity)}</td>
                ${cellsForRow(row).map(value => `<td>${escapeHtml(value)}</td>`).join('')}
              </tr>
            `).join('') : renderEmptyTableRow(headers.length + 2, '暂无数据')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
```

- [ ] **Step 3: Add final result table with no hourly rate**

Replace old final workbench result rendering with:

```javascript
function renderFinalResults(activity) {
  const results = getWorkbenchResults(activity);
  return `
    <section class="step-section final-results">
      <div class="section-head compact">
        <h3>最终结果</h3>
        <button class="btn btn-primary btn-sm" type="button" onclick="exportData('results')" ${results.length ? '' : 'disabled'}>导出结果</button>
      </div>
      <div class="data-table-container">
        <table class="data-table final-result-table">
          <thead>
            <tr>
              <th class="sticky-employee-id">工号</th>
              <th class="sticky-employee-name">姓名</th>
              <th>部门</th>
              <th>岗位</th>
              <th class="metric-cell">绩效得分</th>
              <th class="amount-cell">绩效基数</th>
              <th class="metric-cell">绩效比例</th>
              <th class="metric-cell">绩效系数</th>
              <th class="amount-cell">最终奖金</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            ${results.length ? results.map(result => renderFinalResultRow(result, activity)).join('') : renderEmptyTableRow(10, '暂无结果')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderFinalResultRow(result, activity) {
  const employeeId = String(result.employee_id || '');
  const expanded = state.workbenchSelectedResult === employeeId;
  return `
    <tr>
      <td class="sticky-employee-id">${escapeHtml(employeeId)}</td>
      <td class="sticky-employee-name">${renderNameWithTags(result, activity)}</td>
      <td>${escapeHtml(result.department || result.area || '-')}</td>
      <td>${formatResultJobType(result.job_type)}</td>
      <td class="metric-cell">${formatScore(result.performance_score)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_base)}</td>
      <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
      <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_bonus)}</td>
      <td><button class="btn btn-secondary btn-sm" type="button" onclick="toggleWorkbenchResultDetail(${formatJsArg(employeeId)})">${expanded ? '收起' : '查看说明'}</button></td>
    </tr>
    ${expanded ? renderFinalCalculationDetail(result) : ''}
  `;
}

function renderFinalCalculationDetail(result) {
  const rows = result.calculation_segments || [];
  const detailRows = rows.length ? rows : [{
    period: result.calc_month || '-',
    reason: result.calculation_path || '标准计算',
    performance_base: result.performance_base,
    performance_ratio: result.performance_ratio,
    performance_coefficient: result.performance_coefficient,
    performance_bonus: result.performance_bonus,
  }];
  return `
    <tr class="detail-row">
      <td colspan="10">
        <div class="calculation-lines">
          ${detailRows.map(row => `
            <div class="calculation-line">
              <span>${escapeHtml(row.period || '-')} · ${escapeHtml(row.reason || '-')}</span>
              <strong>${formatCurrency(row.performance_base)} × ${formatPercent(row.performance_ratio)} × ${formatCoefficient(row.performance_coefficient)} = ${formatCurrency(row.performance_bonus)}</strong>
            </div>
          `).join('')}
        </div>
      </td>
    </tr>
  `;
}
```

- [ ] **Step 4: Add compact CSS**

Add to the final refinement CSS block in `fbu-performance.html`:

```css
.activity-stepper {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0;
  border: 1px solid rgba(203, 213, 225, 0.9);
  background: #fff;
}
.activity-step {
  min-width: 0;
  border: 0;
  border-right: 1px solid rgba(226, 232, 240, 0.95);
  background: #fff;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}
.activity-step.active {
  background: #eef2ff;
  box-shadow: inset 0 -2px 0 #4f46e5;
}
.activity-step-index,
.activity-step-summary,
.activity-step-status {
  font-size: 11px;
}
.activity-step-label {
  display: block;
  font-weight: 700;
  color: #111827;
}
.material-row,
.need-row {
  display: grid;
  grid-template-columns: 8px minmax(260px, 1fr) minmax(160px, 280px) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.95);
}
.material-marker {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #94a3b8;
}
.material-row.success .material-marker {
  background: #0f766e;
}
.material-row.warning .material-marker {
  background: #b7791f;
}
.mini-tag,
.person-tag {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 6px;
  border: 1px solid rgba(148, 163, 184, 0.45);
  border-radius: 4px;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 650;
}
.name-with-tags {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.sticky-employee-id,
.sticky-employee-name {
  position: sticky;
  z-index: 2;
  background: inherit;
}
.sticky-employee-id {
  left: 0;
}
.sticky-employee-name {
  left: 104px;
}
.final-result-table .amount-cell,
.final-result-table .metric-cell,
.activity-table .amount-cell,
.activity-table .metric-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 5: Run static and syntax checks**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py -q
node --check bonus_platform/static/fbu-performance.js
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js
git commit -m "feat: add fbu workflow tables and person tags"
```

---

## Task 7: Remove Duplicate Modal-First Workflow Paths and Noisy Copy

**Files:**
- Modify: `bonus_platform/static/fbu-performance.html`
- Modify: `bonus_platform/static/fbu-performance.js`
- Modify: `tests/test_fbu_activity_workflow_static.py`

**Interfaces:**
- Consumes: `openWorkbenchUpload`, `renderPerformanceInlineSupplement`, `renderFinalCalculationDetail`
- Produces: no user-facing upload modal, performance supplement modal, calculation modal, duplicate export buttons, or banned workflow copy

- [ ] **Step 1: Add stricter static assertions**

Append to `tests/test_fbu_activity_workflow_static.py`:

```python
def test_activity_workflow_has_no_modal_first_upload_or_supplement_paths():
    html = _html()
    js = _js()

    assert 'id="uploadModal"' not in html
    assert 'id="performanceSupplementModal"' not in html
    assert 'id="calcChainModal"' not in html
    assert "openUploadModal(" not in js
    assert "openPerformanceSupplementModal(" not in js
    assert "showCalcChain(" not in js


def test_export_button_only_appears_in_final_step_renderer():
    js = _js()

    before_export_step = js.split("function renderExportStep", 1)[0]
    assert "exportData('results')" not in before_export_step
    assert "导出结果" in js.split("function renderExportStep", 1)[1]
```

- [ ] **Step 2: Remove obsolete modal markup**

Remove these blocks from `bonus_platform/static/fbu-performance.html`:

```html
<div class="modal-overlay" id="performanceSupplementModal">...</div>
<div class="modal-overlay" id="uploadModal">...</div>
<div class="modal-overlay" id="calcChainModal">...</div>
```

Keep `appDialog` because it is used for creating a month activity.

- [ ] **Step 3: Remove modal-only JS functions and event branches**

Remove these functions and references from `bonus_platform/static/fbu-performance.js`:

```javascript
openUploadModal
closeUploadModal
handleUploadFileSelect
confirmUpload
openPerformanceSupplementModal
closePerformanceSupplementModal
savePerformanceSupplement
showCalcChain
closeCalcChainModal
```

Keep `openModal`, `closeModal`, and `appDialog` helpers because `btnNewActivity` still uses them.

- [ ] **Step 4: Replace old UI copy in active renderers**

In active render functions, replace:

```text
异常队列 -> 需要处理
导出诊断 -> 导出检查结果
审计明细 -> 查看说明
阻断任务 -> 需要处理
最终合并口径 -> 最终合并结果
```

Do not rename backend JSON keys like `diagnosticsData`; only user-visible Chinese strings need replacement.

- [ ] **Step 5: Run strict UI tests and JS syntax**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py -q
node --check bonus_platform/static/fbu-performance.js
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_fbu_activity_workflow_static.py bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js
git commit -m "refactor: remove duplicate fbu workflow modal paths"
```

---

## Task 8: Browser E2E and Real Activity Regression

**Files:**
- Modify: `tests/test_fbu_activity_workflow_static.py` only if browser findings expose a missing static contract
- Modify: UI files only for verified defects found in this task

**Interfaces:**
- Consumes: local static server for `fbu-performance.html`
- Consumes: existing FBU real E2E script
- Produces: screenshots proving desktop and narrow viewport are usable

- [ ] **Step 1: Run focused automated checks**

Run:

```bash
python3 -m pytest tests/test_fbu_activity_workflow_static.py tests/test_fbu_workbench_static.py tests/test_fbu_rule_list_api.py tests/test_fbu_base_overrides.py tests/test_fbu_supplemental_leave.py tests/test_fbu_shift_split.py -q
node --check bonus_platform/static/fbu-performance.js
```

Expected: all pass.

- [ ] **Step 2: Run existing FBU real E2E**

Run:

```bash
python3 tools/fbu_real_e2e.py --calc-month 2026-04
```

Expected: the script completes; if the script still uploads a generated 96-hour marker workbook through the UI path, update the script to call `POST /api/fbu-performance/runs/{run_id}/rule-lists/confirm` instead.

- [ ] **Step 3: Start local server for browser verification**

Run:

```bash
python3 -m http.server 8002 --directory bonus_platform/static
```

Open:

```text
http://127.0.0.1:8002/fbu-performance.html
```

- [ ] **Step 4: Verify desktop in Playwright**

Use Playwright to capture:

```text
output/fbu_frontend_demo/activity-workflow-desktop.png
```

Viewport: `1440x900`. Check:

- Sidebar is opaque and hover expands smoothly.
- Activity title is compact.
- Six steps are visible without left-side workflow entries.
- Step numbers and summaries are small.
- Current step contains only its upload/material rows.
- No dropdown is needed for the main workflow.

- [ ] **Step 5: Verify narrow desktop/mobile in Playwright**

Use Playwright to capture:

```text
output/fbu_frontend_demo/activity-workflow-narrow.png
```

Viewport: `390x844`. Check:

- Stepper scrolls or wraps without overlapping text.
- Tables keep `工号` and `姓名` fixed.
- Material rows remain readable.
- Buttons do not overflow their containers.

- [ ] **Step 6: Commit verification fixes**

If fixes were required:

```bash
git add bonus_platform/static/fbu-performance.html bonus_platform/static/fbu-performance.js tests/test_fbu_activity_workflow_static.py tools/fbu_real_e2e.py
git commit -m "fix: polish fbu activity workflow verification"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

**Spec coverage:**
- Six-step activity detail: Tasks 3 and 5.
- Sidebar no longer carries FBU workflow steps: Tasks 1 and 3.
- Upload entries are per-step and unique: Tasks 1 and 4.
- Required supplemental leave: Tasks 1, 4, and 5.
- 96-hour employees maintained on page: Tasks 2 and 4.
- Fixed-base employees maintained on page: Tasks 2 and 4.
- Plain-language handling only in current step: Task 5.
- No banned UI wording in active workflow copy: Tasks 1 and 7.
- Tables freeze only employee ID/name: Tasks 1 and 6.
- Special tags beside names: Tasks 1 and 6.
- Final result merged with inline expansion and no hourly rate: Tasks 1 and 6.
- Browser and real E2E verification: Task 8.

**Placeholder scan:**
- The plan intentionally names all files, endpoints, functions, tests, and commands.
- It avoids placeholder markers and vague implementation steps.

**Type consistency:**
- `state.activityStep`, `ACTIVITY_STEPS`, `STEP_MATERIALS`, `renderActivityStepper`, `renderStepContent`, `renderMaintainedRuleList`, `confirmMaintainedRuleList`, `getSpecialPersonTags`, and `renderNameWithTags` are introduced before later tasks depend on them.
- The maintained-list API writes `base_override_data.employees`, matching the existing calculation path consumed by `parse_all_from_step_data`.
