"""FBU绩效核算引擎 - 运行管理"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pathlib import Path
import json
import uuid

from .engines.base import EmployeeData
from .exporter import FBUPerformanceExporter


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


class FBURunManager:
    """FBU运行管理器"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, FBURun] = {}
        self._load_runs()

    def _load_runs(self):
        """加载历史运行记录"""
        runs_file = self.data_dir / "runs.json"
        if runs_file.exists():
            with open(runs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for run_data in data:
                    run = FBURun(**run_data)
                    self.runs[run.run_id] = run

    def _save_runs(self):
        """保存运行记录"""
        runs_file = self.data_dir / "runs.json"
        with open(runs_file, "w", encoding="utf-8") as f:
            json.dump(
                [vars(run) for run in self.runs.values()],
                f,
                ensure_ascii=False,
                indent=2,
            )

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

    def update_run(self, run_id: str, **kwargs):
        """更新运行状态"""
        if run_id in self.runs:
            for key, value in kwargs.items():
                setattr(self.runs[run_id], key, value)
            self._save_runs()

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

    def get_run(self, run_id: str) -> Optional[FBURun]:
        """获取运行记录"""
        return self.runs.get(run_id)

    def list_runs(self) -> list[FBURun]:
        """获取所有运行记录"""
        return sorted(
            self.runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def delete_run(self, run_id: str) -> bool:
        """删除运行记录"""
        if run_id in self.runs:
            del self.runs[run_id]
            self._save_runs()
            return True
        return False

    def save_results(self, run_id: str, employees: list[EmployeeData]):
        """保存核算结果"""
        run = self.get_run(run_id)
        if not run:
            return

        results = []
        total_bonus = 0.0

        for emp in employees:
            results.append({
                "employee_id": emp.employee_id,
                "name": emp.name,
                "job_type": emp.job_type,
                "hourly_rate": emp.hourly_rate,
                "performance_ratio": emp.performance_ratio,
                "base_hours": emp.base_hours,
                "ot15_hours": emp.ot15_hours,
                "ot20_hours": emp.ot20_hours,
                "sick_hours": emp.sick_hours,
                "annual_hours": emp.annual_hours,
                "holiday_hours": emp.holiday_hours,
                "performance_base": emp.performance_base,
                "performance_score": emp.performance_score,
                "performance_level": emp.performance_level,
                "performance_coefficient": emp.performance_coefficient,
                "performance_bonus": emp.performance_bonus,
            })
            total_bonus += emp.performance_bonus

        self.update_run(
            run_id,
            results=results,
            total_employees=len(employees),
            total_bonus=round(total_bonus, 2),
            status="completed",
        )

    def export_run(self, run_id: str, output_dir: str) -> Optional[str]:
        """导出运行结果到Excel"""
        run = self.get_run(run_id)
        if not run or run.status != "completed":
            return None

        # 重建员工数据
        employees = []
        for r in run.results:
            emp = EmployeeData(
                employee_id=r["employee_id"],
                name=r["name"],
                job_type=r["job_type"],
                hourly_rate=r["hourly_rate"],
                performance_ratio=r["performance_ratio"],
                base_hours=r["base_hours"],
                ot15_hours=r["ot15_hours"],
                ot20_hours=r["ot20_hours"],
                sick_hours=r["sick_hours"],
                annual_hours=r["annual_hours"],
                holiday_hours=r["holiday_hours"],
                performance_base=r["performance_base"],
                performance_score=r["performance_score"],
                performance_level=r["performance_level"],
                performance_coefficient=r["performance_coefficient"],
                performance_bonus=r["performance_bonus"],
            )
            employees.append(emp)

        # 导出
        exporter = FBUPerformanceExporter()
        output_path = Path(output_dir) / f"FBU绩效核算_{run.calc_month}_{run_id}.xlsx"

        summary = {
            "核算月份": run.calc_month,
            "员工总数": run.total_employees,
            "绩效奖金总额": f"${run.total_bonus:,.2f}",
            "匹配率": f"{run.match_rate:.1%}",
        }

        return exporter.export_to_excel(employees, str(output_path), summary)
