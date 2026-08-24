"""深圳社保增员报盘 MVP。

已验证范围：北森取数、规则候选、网页人工确认、政务模板映射与报盘导出。
政务站点登录、上传、提交仍由人工控制，当前模块不会伪装成已接入 RPA。
"""

from .runs import (
    RunNotFoundError,
    RunValidationError,
    confirm_run,
    create_run,
    default_reporting_window,
    list_runs,
    load_run,
    update_employee,
)

__all__ = [
    "RunNotFoundError",
    "RunValidationError",
    "confirm_run",
    "create_run",
    "default_reporting_window",
    "list_runs",
    "load_run",
    "update_employee",
]
