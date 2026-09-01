from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlparse

from .. import config
from ..time_utils import utcnow_naive


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  avatar_url TEXT,
  feishu_open_id TEXT,
  feishu_union_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_roles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  module_id TEXT,
  is_system INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_user_roles (
  user_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (user_id) REFERENCES admin_users(id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id)
);

CREATE TABLE IF NOT EXISTS admin_modules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  href TEXT NOT NULL,
  owner_role_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  development_status TEXT NOT NULL DEFAULT 'developing',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_role_module_permissions (
  role_id TEXT NOT NULL,
  module_id TEXT NOT NULL,
  can_enter INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (role_id, module_id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id),
  FOREIGN KEY (module_id) REFERENCES admin_modules(id)
);

CREATE TABLE IF NOT EXISTS admin_role_feature_permissions (
  role_id TEXT NOT NULL,
  feature_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (role_id, feature_id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id)
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES admin_users(id)
);

CREATE TABLE IF NOT EXISTS admin_notification_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  recipient_open_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  message_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS workbench_feedback (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  user_name TEXT NOT NULL,
  user_open_id TEXT,
  category TEXT NOT NULL,
  module_id TEXT NOT NULL,
  module_name TEXT NOT NULL,
  description TEXT NOT NULL,
  page_path TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES admin_users(id)
);

CREATE TABLE IF NOT EXISTS workbench_feedback_attachments (
  id TEXT PRIMARY KEY,
  feedback_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  content BLOB NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (feedback_id) REFERENCES workbench_feedback(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workbench_announcements (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  module_id TEXT NOT NULL,
  module_name TEXT NOT NULL,
  visual_style TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_by_name TEXT NOT NULL,
  published_at TEXT NOT NULL,
  FOREIGN KEY (created_by) REFERENCES admin_users(id)
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  avatar_url TEXT,
  feishu_open_id TEXT,
  feishu_union_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_roles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  module_id TEXT,
  is_system INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_user_roles (
  user_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (user_id) REFERENCES admin_users(id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id)
);

CREATE TABLE IF NOT EXISTS admin_modules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  href TEXT NOT NULL,
  owner_role_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  development_status TEXT NOT NULL DEFAULT 'developing',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_role_module_permissions (
  role_id TEXT NOT NULL,
  module_id TEXT NOT NULL,
  can_enter INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (role_id, module_id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id),
  FOREIGN KEY (module_id) REFERENCES admin_modules(id)
);

CREATE TABLE IF NOT EXISTS admin_role_feature_permissions (
  role_id TEXT NOT NULL,
  feature_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (role_id, feature_id),
  FOREIGN KEY (role_id) REFERENCES admin_roles(id)
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id BIGSERIAL PRIMARY KEY,
  actor_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES admin_users(id)
);

CREATE TABLE IF NOT EXISTS admin_notification_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  recipient_open_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  message_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS workbench_feedback (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  user_name TEXT NOT NULL,
  user_open_id TEXT,
  category TEXT NOT NULL,
  module_id TEXT NOT NULL,
  module_name TEXT NOT NULL,
  description TEXT NOT NULL,
  page_path TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES admin_users(id)
);

CREATE TABLE IF NOT EXISTS workbench_feedback_attachments (
  id TEXT PRIMARY KEY,
  feedback_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  content BYTEA NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (feedback_id) REFERENCES workbench_feedback(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workbench_announcements (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  module_id TEXT NOT NULL,
  module_name TEXT NOT NULL,
  visual_style TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_by_name TEXT NOT NULL,
  published_at TEXT NOT NULL,
  FOREIGN KEY (created_by) REFERENCES admin_users(id)
);
"""


DEFAULT_ROLES = [
    {"id": "admin", "name": "系统管理员", "module_id": None, "is_system": 1},
    {"id": "recruitmentAdmin", "name": "招聘奖金核算管理员", "module_id": "recruitment", "is_system": 0},
    {"id": "employeeAdmin", "name": "国内正式工核算管理员", "module_id": "employee", "is_system": 0},
    {"id": "domesticAdmin", "name": "国内外包工核算管理员", "module_id": "domestic", "is_system": 0},
    {"id": "fbuAdmin", "name": "海外薪酬核算管理员", "module_id": "fbu", "is_system": 0},
    {"id": "overseasAdmin", "name": "海外劳务报账核对管理员", "module_id": "overseas", "is_system": 0},
    {"id": "socialInsuranceAdmin", "name": "社保报盘管理员", "module_id": "social_insurance", "is_system": 0},
]

DEFAULT_USERS = [
    {"id": "payrollAdmin", "name": "Payroll Admin", "email": "payroll.admin@example.com", "role_ids": ["admin"]},
    {"id": "recruitmentAdminUser", "name": "Recruitment Admin", "email": "recruitment.admin@example.com", "role_ids": ["recruitmentAdmin"]},
    {"id": "cnPayrollAdminUser", "name": "CN Payroll Admin", "email": "cn.payroll.admin@example.com", "role_ids": ["employeeAdmin", "domesticAdmin", "socialInsuranceAdmin"]},
    {"id": "fbuAdminUser", "name": "FBU Bonus Admin", "email": "fbu.admin@example.com", "role_ids": ["fbuAdmin"]},
    {"id": "overseasAdminUser", "name": "Overseas Audit Admin", "email": "overseas.admin@example.com", "role_ids": ["overseasAdmin"]},
]

DEFAULT_WORKBENCH_ANNOUNCEMENTS = [
    {
        "id": "UPD-LAUNCH-RECRUITMENT-20260820",
        "kind": "feature",
        "title": "招聘奖金核算已上线",
        "content": (
            "每月招聘奖金可以在一个页面里完成。\n"
            "- 导入本月资料并完成初算\n"
            "- 查看差异并确认结果\n"
            "- 确认后导出结果，留存本月记录\n"
            "> 建议按“导入—检查—确认—留存”的顺序使用。"
        ),
        "module_id": "recruitment",
        "module_name": "全球招聘奖金核算",
        "visual_style": "sunny",
        "created_by": "payrollAdmin",
        "created_by_name": "HRAS 工作台",
        "published_at": "2026-08-20T01:00:00Z",
    },
    {
        "id": "UPD-LAUNCH-EMPLOYEE-20260820",
        "kind": "feature",
        "title": "正式工餐补核算已开放",
        "content": (
            "正式工模块现已开放餐补核算。\n"
            "- 导入集团与 WX 考勤资料\n"
            "- 按月份计算餐补\n"
            "- 查看缺失、重复等需要核对的记录\n"
            "- 确认后导出结果\n"
            "> 当前先开放餐补，其他薪酬项目会按计划增加。"
        ),
        "module_id": "employee",
        "module_name": "中国区正式工薪酬核算",
        "visual_style": "mint",
        "created_by": "payrollAdmin",
        "created_by_name": "HRAS 工作台",
        "published_at": "2026-08-20T01:01:00Z",
    },
    {
        "id": "UPD-LAUNCH-DOMESTIC-20260820",
        "kind": "feature",
        "title": "外包工薪酬核算开放试用",
        "content": (
            "现在可以按月完成外包工考勤和薪酬核算。\n"
            "- 导入考勤资料\n"
            "- 核算各项薪酬\n"
            "- 查看员工明细和需要复核的记录\n"
            "- 导出核算结果\n"
            "> 目前处于试用阶段，正式使用前请复核结果。"
        ),
        "module_id": "domestic",
        "module_name": "中国区外包工薪酬核算",
        "visual_style": "blueprint",
        "created_by": "payrollAdmin",
        "created_by_name": "HRAS 工作台",
        "published_at": "2026-08-20T01:02:00Z",
    },
    {
        "id": "UPD-LAUNCH-FBU-20260820",
        "kind": "feature",
        "title": "FBU绩效奖金核算已上线",
        "content": (
            "FBU 每月绩效奖金可以集中处理。\n"
            "- 上传当月薪资、全量调薪和上月薪资\n"
            "- 查看绩效数据并进行核算检查\n"
            "- 在不同页面之间切换时，已上传资料会继续保留\n"
            "- 复核后查看最终结果\n"
            "> 刷新页面后，上月薪资仍会保留。"
        ),
        "module_id": "fbu",
        "module_name": "FBU美洲绩效奖金核算",
        "visual_style": "peach",
        "created_by": "payrollAdmin",
        "created_by_name": "HRAS 工作台",
        "published_at": "2026-08-20T01:03:00Z",
    },
    {
        "id": "UPD-LAUNCH-OVERSEAS-20260820",
        "kind": "feature",
        "title": "海外报账核对开放试用",
        "content": (
            "海外劳务报账资料可以在一个页面完成核对。\n"
            "- 上传发票和报账表\n"
            "- 按员工查看资料是否一致\n"
            "- 集中查看金额、工时和人员信息差异\n"
            "- 确认后下载核对结果\n"
            "> 请先确认发票清晰、报账表信息完整。"
        ),
        "module_id": "overseas",
        "module_name": "海外劳务报账核对",
        "visual_style": "sunny",
        "created_by": "payrollAdmin",
        "created_by_name": "HRAS 工作台",
        "published_at": "2026-08-20T01:04:00Z",
    },
]

DEFAULT_MODULES = [
    {"id": "recruitment", "name": "全球招聘奖金核算", "href": "recruitment.html", "owner_role_id": "recruitmentAdmin", "enabled": 1, "development_status": "available"},
    {"id": "employee", "name": "中国区正式工薪酬核算", "href": "china-employee-payroll.html", "owner_role_id": "employeeAdmin", "enabled": 1, "development_status": "available"},
    {"id": "domestic", "name": "中国区外包工薪酬核算", "href": "domestic-labor.html", "owner_role_id": "domesticAdmin", "enabled": 1, "development_status": "uat"},
    {"id": "fbu", "name": "FBU美洲绩效奖金核算", "href": "fbu-performance.html", "owner_role_id": "fbuAdmin", "enabled": 1, "development_status": "available"},
    {"id": "overseas_payroll", "name": "海外薪资工作台", "href": "overseas-payroll.html", "owner_role_id": "fbuAdmin", "enabled": 1, "development_status": "available"},
    {"id": "overseas", "name": "海外劳务报账核对", "href": "overseas-labor.html", "owner_role_id": "overseasAdmin", "enabled": 1, "development_status": "uat"},
    {"id": "social_insurance", "name": "社保报盘工作台", "href": "social-insurance.html", "owner_role_id": "socialInsuranceAdmin", "enabled": 1, "development_status": "uat"},
]

OPEN_FOR_RELEASE_MODULE_IDS = {"recruitment", "employee", "domestic", "fbu", "overseas_payroll", "overseas", "social_insurance"}
CLOSED_UNTIL_RELEASE_MODULE_IDS: set[str] = set()

DEFAULT_ROLE_MODULE_GRANTS = {
    "fbuAdmin": {"overseas_payroll"},
}

DEFAULT_FEATURES = ["enter", "import", "calculate", "review", "export", "archive", "audit"]
SESSION_TTL_DAYS = 7
_STORE_INITIALIZED = False
_STORE_INITIALIZED_TARGET = ""


def get_admin_db_path() -> Path:
    return config.DATABASE_PATH


def get_admin_database_url() -> str:
    database_url = str(getattr(config, "ADMIN_DATABASE_URL", "") or "")
    return re.sub(r"\[([A-Za-z0-9.-]*supabase\.com)\]", r"\1", database_url)


def _database_backend(db_path: Path | None = None) -> str:
    if db_path is not None:
        return "sqlite"
    database_url = get_admin_database_url().strip()
    if not database_url:
        return "sqlite"
    if database_url.startswith(("postgres://", "postgresql://")):
        return "postgres"
    if database_url.startswith("sqlite://"):
        return "sqlite"
    scheme = database_url.split(":", 1)[0]
    raise RuntimeError(f"Unsupported ADMIN_DATABASE_URL scheme: {scheme or 'empty'}")


def _sqlite_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return db_path
    database_url = get_admin_database_url().strip()
    if database_url.startswith("sqlite:///"):
        return Path(urlparse(database_url).path).expanduser().resolve()
    return get_admin_db_path()


def _now() -> str:
    return utcnow_naive().replace(microsecond=0).isoformat() + "Z"


def _expires_at() -> str:
    return (utcnow_naive().replace(microsecond=0) + timedelta(days=SESSION_TTL_DAYS)).isoformat() + "Z"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _postgres_connection(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Postgres admin store requires installing psycopg[binary]") from exc
    return psycopg.connect(database_url, row_factory=dict_row, prepare_threshold=None, connect_timeout=5)


class _AdminConnection:
    def __init__(self, raw_connection: Any, backend: str):
        self.raw_connection = raw_connection
        self.backend = backend

    def __enter__(self) -> "_AdminConnection":
        self.raw_connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        return self.raw_connection.__exit__(exc_type, exc, traceback)

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        if self.backend == "postgres":
            sql = sql.replace("?", "%s")
        return self.raw_connection.execute(sql, params)

    def executescript(self, script: str) -> None:
        if self.backend == "sqlite":
            self.raw_connection.executescript(script)
            return
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def commit(self) -> None:
        self.raw_connection.commit()

    def rollback(self) -> None:
        self.raw_connection.rollback()


def _connect(db_path: Path | None = None) -> _AdminConnection:
    backend = _database_backend(db_path)
    if backend == "postgres":
        return _AdminConnection(_postgres_connection(get_admin_database_url()), "postgres")
    path = _sqlite_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return _AdminConnection(connection, "sqlite")


def init_admin_store(db_path: Path | None = None) -> Path | str:
    global _STORE_INITIALIZED, _STORE_INITIALIZED_TARGET
    backend = _database_backend(db_path)
    target = get_admin_database_url() if backend == "postgres" else str(_sqlite_db_path(db_path))
    if db_path is None and _STORE_INITIALIZED and _STORE_INITIALIZED_TARGET == target:
        return target
    with _connect(db_path) as connection:
        if backend == "postgres":
            connection.execute("SELECT pg_advisory_xact_lock(917137)")
        try:
            connection.executescript(POSTGRES_SCHEMA if backend == "postgres" else SQLITE_SCHEMA)
            _migrate_schema(connection)
            _seed_defaults(connection)
            _migrate_default_role_module_grants(connection)
            connection.commit()
            if db_path is None:
                _STORE_INITIALIZED = True
                _STORE_INITIALIZED_TARGET = target
        except Exception:
            connection.rollback()
            raise
    return get_admin_database_url() if backend == "postgres" else _sqlite_db_path(db_path)


def admin_store_health() -> dict[str, Any]:
    backend = _database_backend()
    configured = backend == "postgres" and bool(get_admin_database_url().strip())
    if not configured:
        return {"backend": backend, "configured": False, "ready": False}
    try:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT
                  to_regclass('public.admin_users') IS NOT NULL AS users_ready,
                  to_regclass('public.admin_roles') IS NOT NULL AS roles_ready,
                  to_regclass('public.admin_user_roles') IS NOT NULL AS user_roles_ready,
                  to_regclass('public.admin_sessions') IS NOT NULL AS sessions_ready
                """
            ).fetchone()
        values = dict(row or {})
        ready = all(
            bool(values.get(key))
            for key in ("users_ready", "roles_ready", "user_roles_ready", "sessions_ready")
        )
        return {"backend": "postgres", "configured": True, "ready": ready}
    except Exception as exc:  # noqa: BLE001 - health output must stay sanitized.
        return {
            "backend": "postgres",
            "configured": True,
            "ready": False,
            "error": str(exc).replace("\n", " ")[:240],
        }


def _column_exists(connection: _AdminConnection, table: str, column: str) -> bool:
    if connection.backend == "postgres":
        row = connection.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (table, column),
        ).fetchone()
        return bool(row)
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _migrate_schema(connection: _AdminConnection) -> None:
    if not _column_exists(connection, "admin_users", "avatar_url"):
        connection.execute("ALTER TABLE admin_users ADD COLUMN avatar_url TEXT")


def _insert_seed(connection: _AdminConnection, table: str, columns: list[str], conflict_columns: list[str], values: dict[str, Any]) -> None:
    column_sql = ", ".join(columns)
    if connection.backend == "postgres":
        placeholder_sql = ", ".join("%s" for _ in columns)
        conflict_sql = ", ".join(conflict_columns)
        connection.execute(
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholder_sql}) ON CONFLICT ({conflict_sql}) DO NOTHING",
            tuple(values[column] for column in columns),
        )
        return
    placeholder_sql = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR IGNORE INTO {table} ({column_sql}) VALUES ({placeholder_sql})",
        tuple(values[column] for column in columns),
    )


def _seed_defaults(connection: _AdminConnection) -> None:
    now = _now()
    for role in DEFAULT_ROLES:
        _insert_seed(
            connection,
            "admin_roles",
            ["id", "name", "module_id", "is_system", "created_at", "updated_at"],
            ["id"],
            {**role, "created_at": now, "updated_at": now},
        )
        parameters = (role["name"], role.get("module_id"), role["is_system"], now, role["id"])
        if connection.backend == "postgres":
            connection.execute(
                """
                UPDATE admin_roles
                SET name = %s, module_id = %s, is_system = %s, updated_at = %s
                WHERE id = %s
                """,
                parameters,
            )
        else:
            connection.execute(
                """
                UPDATE admin_roles
                SET name = ?, module_id = ?, is_system = ?, updated_at = ?
                WHERE id = ?
                """,
                parameters,
            )
    for module in DEFAULT_MODULES:
        _insert_seed(
            connection,
            "admin_modules",
            ["id", "name", "href", "owner_role_id", "enabled", "development_status", "created_at", "updated_at"],
            ["id"],
            {**module, "created_at": now, "updated_at": now},
        )
        if connection.backend == "postgres":
            connection.execute(
                """
                UPDATE admin_modules
                SET name = %s, href = %s, owner_role_id = %s, development_status = %s, updated_at = %s
                WHERE id = %s
                """,
                (module["name"], module["href"], module["owner_role_id"], module["development_status"], now, module["id"]),
            )
            if module["id"] in CLOSED_UNTIL_RELEASE_MODULE_IDS:
                connection.execute(
                    "UPDATE admin_modules SET enabled = %s, updated_at = %s WHERE id = %s",
                    (0, now, module["id"]),
                )
            elif module["id"] in OPEN_FOR_RELEASE_MODULE_IDS:
                connection.execute(
                    "UPDATE admin_modules SET enabled = %s, updated_at = %s WHERE id = %s",
                    (1, now, module["id"]),
                )
        else:
            connection.execute(
                """
                UPDATE admin_modules
                SET name = ?, href = ?, owner_role_id = ?, development_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (module["name"], module["href"], module["owner_role_id"], module["development_status"], now, module["id"]),
            )
            if module["id"] in CLOSED_UNTIL_RELEASE_MODULE_IDS:
                connection.execute(
                    "UPDATE admin_modules SET enabled = ?, updated_at = ? WHERE id = ?",
                    (0, now, module["id"]),
                )
            elif module["id"] in OPEN_FOR_RELEASE_MODULE_IDS:
                connection.execute(
                    "UPDATE admin_modules SET enabled = ?, updated_at = ? WHERE id = ?",
                    (1, now, module["id"]),
                )
    for user in DEFAULT_USERS:
        _insert_seed(
            connection,
            "admin_users",
            ["id", "name", "email", "status", "created_at", "updated_at"],
            ["id"],
            {**user, "status": "active", "created_at": now, "updated_at": now},
        )
        for role_id in user["role_ids"]:
            _insert_seed(
                connection,
                "admin_user_roles",
                ["user_id", "role_id", "created_at"],
                ["user_id", "role_id"],
                {"user_id": user["id"], "role_id": role_id, "created_at": now},
            )
    for announcement in DEFAULT_WORKBENCH_ANNOUNCEMENTS:
        _insert_seed(
            connection,
            "workbench_announcements",
            [
                "id",
                "kind",
                "title",
                "content",
                "module_id",
                "module_name",
                "visual_style",
                "created_by",
                "created_by_name",
                "published_at",
            ],
            ["id"],
            announcement,
        )
    for role in DEFAULT_ROLES:
        for module in DEFAULT_MODULES:
            explicit_grants = DEFAULT_ROLE_MODULE_GRANTS.get(role["id"], set())
            can_enter = 1 if (
                role["id"] == "admin"
                or role.get("module_id") == module["id"]
                or module["id"] in explicit_grants
            ) else 0
            _insert_seed(
                connection,
                "admin_role_module_permissions",
                ["role_id", "module_id", "can_enter", "updated_at"],
                ["role_id", "module_id"],
                {"role_id": role["id"], "module_id": module["id"], "can_enter": can_enter, "updated_at": now},
            )
        for feature_id in DEFAULT_FEATURES:
            enabled = 1 if role["id"] == "admin" or feature_id in {"enter", "import", "calculate", "review"} else 0
            _insert_seed(
                connection,
                "admin_role_feature_permissions",
                ["role_id", "feature_id", "enabled", "updated_at"],
                ["role_id", "feature_id"],
                {"role_id": role["id"], "feature_id": feature_id, "enabled": enabled, "updated_at": now},
            )


def _migrate_default_role_module_grants(connection: _AdminConnection) -> None:
    """Apply each bundled-scope migration once, then preserve later admin choices."""
    now = _now()
    for role_id, module_ids in DEFAULT_ROLE_MODULE_GRANTS.items():
        for module_id in module_ids:
            target_id = f"{module_id}:{role_id}"
            already_migrated = connection.execute(
                """
                SELECT 1
                FROM admin_audit_logs
                WHERE action = ? AND target_type = ? AND target_id = ?
                LIMIT 1
                """,
                ("migrate_default_role_module_grant", "module_role", target_id),
            ).fetchone()
            if already_migrated:
                continue
            connection.execute(
                """
                UPDATE admin_role_module_permissions
                SET can_enter = ?, updated_at = ?
                WHERE role_id = ? AND module_id = ?
                """,
                (1, now, role_id, module_id),
            )
            _insert_audit(
                connection,
                "system",
                "migrate_default_role_module_grant",
                "module_role",
                target_id,
                "can_enter=true",
            )


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _notification_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    try:
        payload = json.loads(str(data.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        payload = {}
    return {
        "id": str(data.get("id") or ""),
        "eventKey": str(data.get("event_key") or ""),
        "kind": str(data.get("kind") or ""),
        "recipientOpenId": str(data.get("recipient_open_id") or ""),
        "payload": payload if isinstance(payload, dict) else {},
        "status": str(data.get("status") or "pending"),
        "attemptCount": int(data.get("attempt_count") or 0),
        "lastError": str(data.get("last_error") or ""),
        "messageId": str(data.get("message_id") or ""),
        "createdAt": str(data.get("created_at") or ""),
        "updatedAt": str(data.get("updated_at") or ""),
        "sentAt": str(data.get("sent_at") or ""),
    }


def enqueue_admin_notification(
    *,
    event_key: str,
    kind: str,
    recipient_open_id: str,
    payload: dict[str, Any],
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Persist a deduplicated notification before attempting external delivery."""
    init_admin_store(db_path)
    now = _now()
    notification_id = secrets.token_hex(16)
    with _connect(db_path) as connection:
        _insert_seed(
            connection,
            "admin_notification_outbox",
            [
                "id", "event_key", "kind", "recipient_open_id", "payload_json",
                "status", "attempt_count", "created_at", "updated_at",
            ],
            ["event_key"],
            {
                "id": notification_id,
                "event_key": event_key,
                "kind": kind,
                "recipient_open_id": recipient_open_id,
                "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "status": "pending",
                "attempt_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = connection.execute(
            "SELECT * FROM admin_notification_outbox WHERE event_key = ?",
            (event_key,),
        ).fetchone()
        connection.commit()
    if not row:
        raise RuntimeError("notification_outbox_insert_failed")
    return _notification_from_row(row)


def get_admin_notification(notification_id: str, db_path: Path | None = None) -> dict[str, Any]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM admin_notification_outbox WHERE id = ?",
            (notification_id,),
        ).fetchone()
    if not row:
        raise KeyError("notification_not_found")
    return _notification_from_row(row)


def list_pending_admin_notifications(
    limit: int = 3,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    safe_limit = max(1, min(int(limit or 1), 20))
    stale_before = (
        utcnow_naive().replace(microsecond=0) - timedelta(minutes=5)
    ).isoformat() + "Z"
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM admin_notification_outbox
            WHERE status = 'pending'
               OR (status = 'sending' AND updated_at < ?)
            ORDER BY created_at, id
            LIMIT ?
            """,
            (stale_before, safe_limit),
        ).fetchall()
    return [_notification_from_row(row) for row in rows]


def claim_admin_notification(notification_id: str, db_path: Path | None = None) -> bool:
    """Atomically lease one outbox row so concurrent requests cannot double-send it."""
    init_admin_store(db_path)
    now = _now()
    stale_before = (
        utcnow_naive().replace(microsecond=0) - timedelta(minutes=5)
    ).isoformat() + "Z"
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE admin_notification_outbox
            SET status = 'sending', updated_at = ?
            WHERE id = ?
              AND (status = 'pending' OR (status = 'sending' AND updated_at < ?))
            """,
            (now, notification_id, stale_before),
        )
        claimed = bool(cursor.rowcount)
        connection.commit()
    return claimed


def mark_admin_notification_failed(
    notification_id: str,
    error: str,
    db_path: Path | None = None,
) -> None:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE admin_notification_outbox
            SET status = 'pending', attempt_count = attempt_count + 1,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(error or "notification_failed").replace("\n", " ")[:500], _now(), notification_id),
        )
        connection.commit()


def mark_admin_notification_sent(
    notification_id: str,
    message_id: str,
    db_path: Path | None = None,
) -> None:
    init_admin_store(db_path)
    now = _now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE admin_notification_outbox
            SET status = 'sent', attempt_count = attempt_count + 1,
                last_error = NULL, message_id = ?, updated_at = ?, sent_at = ?
            WHERE id = ?
            """,
            (message_id, now, now, notification_id),
        )
        connection.commit()


def list_roles(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            'SELECT id, name, module_id AS "moduleId", is_system AS "isSystem" FROM admin_roles ORDER BY is_system DESC, id'
        ).fetchall()
    return [
        {**dict(row), "isSystem": bool(row["isSystem"])}
        for row in rows
    ]


def list_modules(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT m.id, m.name, m.href, m.enabled, m.development_status AS "developmentStatus",
                   m.owner_role_id AS "ownerRoleId", r.name AS "ownerRoleName"
            FROM admin_modules m
            LEFT JOIN admin_roles r ON r.id = m.owner_role_id
            ORDER BY CASE m.id
              WHEN 'recruitment' THEN 1 WHEN 'employee' THEN 2 WHEN 'domestic' THEN 3
              WHEN 'fbu' THEN 4 WHEN 'overseas_payroll' THEN 5 WHEN 'overseas' THEN 6
              WHEN 'social_insurance' THEN 7 ELSE 99 END
            """
        ).fetchall()
    return [
        {
            **dict(row),
            "enabled": (
                row["id"] in OPEN_FOR_RELEASE_MODULE_IDS
                or (bool(row["enabled"]) and row["id"] not in CLOSED_UNTIL_RELEASE_MODULE_IDS)
            ),
        }
        for row in rows
    ]


def list_users(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        users = _rows_to_dicts(connection.execute(
            'SELECT id, name, email, avatar_url AS "avatarUrl", feishu_open_id AS "feishuOpenId", feishu_union_id AS "feishuUnionId", status FROM admin_users ORDER BY id'
        ).fetchall())
        role_rows = connection.execute("SELECT user_id, role_id FROM admin_user_roles ORDER BY role_id").fetchall()
    role_map: dict[str, list[str]] = {}
    for row in role_rows:
        role_map.setdefault(row["user_id"], []).append(row["role_id"])
    return [{**user, "roleIds": role_map.get(user["id"], [])} for user in users]


def get_permissions(db_path: Path | None = None) -> dict[str, Any]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        module_rows = connection.execute(
            "SELECT role_id, module_id, can_enter FROM admin_role_module_permissions"
        ).fetchall()
        feature_rows = connection.execute(
            "SELECT role_id, feature_id, enabled FROM admin_role_feature_permissions"
        ).fetchall()
    module_access: dict[str, dict[str, bool]] = {}
    for row in module_rows:
        module_access.setdefault(row["role_id"], {})[row["module_id"]] = bool(row["can_enter"])
    role_permissions: dict[str, dict[str, bool]] = {}
    for row in feature_rows:
        role_permissions.setdefault(row["role_id"], {})[row["feature_id"]] = bool(row["enabled"])
    return {"moduleAccess": module_access, "rolePermissions": role_permissions}


def get_admin_state(db_path: Path | None = None) -> dict[str, Any]:
    return {
        "users": list_users(db_path),
        "roles": list_roles(db_path),
        "modules": list_modules(db_path),
        **get_permissions(db_path),
    }


def _bootstrap_admin_identifiers() -> set[str]:
    return {identifier.casefold() for identifier in config.ADMIN_BOOTSTRAP_IDENTIFIERS if identifier}


def _user_matches_bootstrap_admin(user: dict[str, Any]) -> bool:
    identifiers = _bootstrap_admin_identifiers()
    if not identifiers:
        return False
    values = {
        str(user.get("id") or ""),
        str(user.get("name") or ""),
        str(user.get("email") or ""),
        str(user.get("feishuOpenId") or ""),
        str(user.get("feishuUnionId") or ""),
    }
    return any(value.casefold() in identifiers for value in values if value)


def ensure_bootstrap_admin_for_user(user_id: str, db_path: Path | None = None) -> None:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        user = connection.execute(
            """
            SELECT id, name, email, avatar_url AS "avatarUrl", feishu_open_id AS "feishuOpenId", feishu_union_id AS "feishuUnionId"
            FROM admin_users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if not user:
            return
        user_dict = dict(user)
        if not _user_matches_bootstrap_admin(user_dict):
            return
        if connection.execute(
            "SELECT 1 FROM admin_user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, "admin"),
        ).fetchone():
            return
        now = _now()
        connection.execute(
            "INSERT INTO admin_user_roles (user_id, role_id, created_at) VALUES (?, ?, ?)",
            (user_id, "admin", now),
        )
        connection.execute("UPDATE admin_users SET status = 'active', updated_at = ? WHERE id = ?", (now, user_id))
        _insert_audit(connection, "system", "bootstrap_admin", "user", user_id, "admin")
        connection.commit()


def get_current_user(user_id: str = "payrollAdmin", db_path: Path | None = None) -> dict[str, Any]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        user_row = connection.execute(
            """
            SELECT id, name, email, avatar_url AS "avatarUrl",
                   feishu_open_id AS "feishuOpenId", feishu_union_id AS "feishuUnionId", status
            FROM admin_users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if not user_row:
            raise KeyError("user_not_found")
        user = dict(user_row)

        if _user_matches_bootstrap_admin(user) and not connection.execute(
            "SELECT 1 FROM admin_user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, "admin"),
        ).fetchone():
            now = _now()
            connection.execute(
                "INSERT INTO admin_user_roles (user_id, role_id, created_at) VALUES (?, ?, ?)",
                (user_id, "admin", now),
            )
            connection.execute(
                "UPDATE admin_users SET status = 'active', updated_at = ? WHERE id = ?",
                (now, user_id),
            )
            _insert_audit(connection, "system", "bootstrap_admin", "user", user_id, "admin")
            connection.commit()
            user["status"] = "active"

        role_rows = connection.execute(
            """
            SELECT r.id, r.name, r.module_id AS "moduleId", r.is_system AS "isSystem"
            FROM admin_roles r
            JOIN admin_user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = ?
            ORDER BY r.is_system DESC, r.id
            """,
            (user_id,),
        ).fetchall()
        roles = [{**dict(row), "isSystem": bool(row["isSystem"])} for row in role_rows]
        role_ids = [str(role["id"]) for role in roles]
        user["roleIds"] = role_ids

        module_rows = connection.execute(
            """
            SELECT m.id, m.name, m.href, m.enabled, m.development_status AS "developmentStatus",
                   m.owner_role_id AS "ownerRoleId", r.name AS "ownerRoleName"
            FROM admin_modules m
            LEFT JOIN admin_roles r ON r.id = m.owner_role_id
            ORDER BY CASE m.id
              WHEN 'recruitment' THEN 1 WHEN 'employee' THEN 2 WHEN 'domestic' THEN 3
              WHEN 'fbu' THEN 4 WHEN 'overseas' THEN 5 ELSE 99 END
            """
        ).fetchall()
        modules = [
            {
                **dict(row),
                "enabled": (
                    row["id"] in OPEN_FOR_RELEASE_MODULE_IDS
                    or (bool(row["enabled"]) and row["id"] not in CLOSED_UNTIL_RELEASE_MODULE_IDS)
                ),
            }
            for row in module_rows
        ]

        module_access = {role_id: {} for role_id in role_ids}
        role_permissions = {role_id: {} for role_id in role_ids}
        if role_ids:
            placeholders = ",".join("?" for _ in role_ids)
            for row in connection.execute(
                f"""
                SELECT role_id, module_id, can_enter
                FROM admin_role_module_permissions
                WHERE role_id IN ({placeholders})
                """,
                role_ids,
            ).fetchall():
                module_access[str(row["role_id"])][str(row["module_id"])] = bool(row["can_enter"])
            for row in connection.execute(
                f"""
                SELECT role_id, feature_id, enabled
                FROM admin_role_feature_permissions
                WHERE role_id IN ({placeholders})
                """,
                role_ids,
            ).fetchall():
                role_permissions[str(row["role_id"])][str(row["feature_id"])] = bool(row["enabled"])

    allowed_modules = []
    for module in modules:
        can_enter = module["enabled"] and any(
            module_access.get(role_id, {}).get(module["id"])
            and role_permissions.get(role_id, {}).get("enter")
            for role_id in role_ids
        )
        allowed_modules.append({**module, "canEnter": bool(can_enter)})
    return {
        "user": user,
        "roles": roles,
        "modules": allowed_modules,
        "permissions": {
            "moduleAccess": module_access,
            "rolePermissions": role_permissions,
        },
    }


def create_session(user_id: str, db_path: Path | None = None, action: str = "mock_login") -> str:
    init_admin_store(db_path)
    token = secrets.token_urlsafe(32)
    now = _now()
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM admin_users WHERE id = ?", (user_id,)).fetchone():
            raise KeyError("user_not_found")
        connection.execute(
            """
            INSERT INTO admin_sessions (token_hash, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (_hash_token(token), user_id, now, _expires_at()),
        )
        _insert_audit(connection, user_id, action, "user", user_id, "session_created")
        connection.commit()
    return token


def upsert_feishu_user(
    *,
    feishu_open_id: str,
    feishu_union_id: str | None = None,
    email: str | None = None,
    avatar_url: str | None = None,
    name: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    init_admin_store(db_path)
    now = _now()
    with _connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id FROM admin_users
            WHERE feishu_open_id = ?
               OR (feishu_union_id IS NOT NULL AND feishu_union_id = ?)
               OR (email IS NOT NULL AND email = ?)
            LIMIT 1
            """,
            (feishu_open_id, feishu_union_id, email),
        ).fetchone()
        user_id = str(existing["id"]) if existing else f"feishu_{feishu_open_id}"
        if existing:
            connection.execute(
                """
                UPDATE admin_users
                SET name = COALESCE(?, name),
                    email = COALESCE(?, email),
                    avatar_url = COALESCE(?, avatar_url),
                    feishu_open_id = ?,
                    feishu_union_id = COALESCE(?, feishu_union_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (name, email, avatar_url, feishu_open_id, feishu_union_id, now, user_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO admin_users (
                  id, name, email, avatar_url, feishu_open_id, feishu_union_id, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (user_id, name or email or feishu_open_id, email, avatar_url, feishu_open_id, feishu_union_id, now, now),
            )
        _insert_audit(connection, user_id, "feishu_user_upsert", "user", user_id, email or feishu_open_id)
        connection.commit()
    ensure_bootstrap_admin_for_user(user_id, db_path)
    result = next(user for user in list_users(db_path) if user["id"] == user_id)
    result["_created"] = not bool(existing)
    return result


def get_session_user_id(token: str, db_path: Path | None = None) -> str:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT user_id FROM admin_sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (_hash_token(token), _now()),
        ).fetchone()
    if not row:
        raise KeyError("session_not_found")
    return str(row["user_id"])


def get_session_auth_context(token: str, db_path: Path | None = None) -> tuple[str, str]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT s.user_id,
                   u.status AS user_status,
                   u.updated_at AS user_updated_at,
                   ur.role_id,
                   m.id AS module_id,
                   m.enabled AS module_enabled,
                   m.updated_at AS module_updated_at,
                   rmp.can_enter,
                   rmp.updated_at AS module_permission_updated_at,
                   rfp.feature_id,
                   rfp.enabled AS feature_enabled,
                   rfp.updated_at AS feature_permission_updated_at
            FROM admin_sessions s
            JOIN admin_users u ON u.id = s.user_id
            CROSS JOIN admin_modules m
            LEFT JOIN admin_user_roles ur ON ur.user_id = s.user_id
            LEFT JOIN admin_role_module_permissions rmp
              ON rmp.role_id = ur.role_id AND rmp.module_id = m.id
            LEFT JOIN admin_role_feature_permissions rfp ON rfp.role_id = ur.role_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            ORDER BY COALESCE(ur.role_id, ''), m.id, COALESCE(rfp.feature_id, '')
            """,
            (_hash_token(token), _now()),
        ).fetchall()
    if not rows:
        raise KeyError("session_not_found")
    revision_fields = (
        "user_status",
        "user_updated_at",
        "role_id",
        "module_id",
        "module_enabled",
        "module_updated_at",
        "can_enter",
        "module_permission_updated_at",
        "feature_id",
        "feature_enabled",
        "feature_permission_updated_at",
    )
    revision = hashlib.sha256(
        "\n".join(
            "|".join(str(row[field] or "") for field in revision_fields)
            for row in rows
        ).encode("utf-8")
    ).hexdigest()
    return str(rows[0]["user_id"]), revision


def delete_session(token: str, db_path: Path | None = None) -> None:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        session = connection.execute(
            "SELECT user_id FROM admin_sessions WHERE token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
        connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_hash_token(token),))
        if session:
            user_id = str(session["user_id"])
            _insert_audit(connection, user_id, "logout", "user", user_id, "登录会话已退出")
        connection.commit()


def set_user_roles(user_id: str, role_ids: list[str], actor_user_id: str = "payrollAdmin", db_path: Path | None = None) -> dict[str, Any]:
    init_admin_store(db_path)
    now = _now()
    with _connect(db_path) as connection:
        user = connection.execute("SELECT id FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise KeyError("user_not_found")
        valid_roles = {
            row["id"] for row in connection.execute(
                "SELECT id FROM admin_roles WHERE id IN ({})".format(",".join("?" for _ in role_ids) or "''"),
                role_ids,
            ).fetchall()
        }
        if set(role_ids) != valid_roles:
            raise KeyError("role_not_found")
        admin_rows = connection.execute("SELECT user_id FROM admin_user_roles WHERE role_id = ?", ("admin",)).fetchall()
        admin_user_ids = {row["user_id"] for row in admin_rows}
        removing_admin = user_id in admin_user_ids and "admin" not in role_ids
        if removing_admin and user_id == actor_user_id:
            raise ValueError("cannot_remove_own_admin")
        if removing_admin and len(admin_user_ids) <= 1:
            raise ValueError("cannot_remove_last_admin")
        connection.execute("DELETE FROM admin_user_roles WHERE user_id = ?", (user_id,))
        for role_id in role_ids:
            connection.execute(
                "INSERT INTO admin_user_roles (user_id, role_id, created_at) VALUES (?, ?, ?)",
                (user_id, role_id, now),
            )
        next_status = "active" if role_ids else "pending"
        connection.execute("UPDATE admin_users SET status = ?, updated_at = ? WHERE id = ?", (next_status, now, user_id))
        _insert_audit(connection, actor_user_id, "set_user_roles", "user", user_id, ",".join(role_ids))
        connection.commit()
    return next(user for user in list_users(db_path) if user["id"] == user_id)


def set_module_enabled(module_id: str, enabled: bool, actor_user_id: str = "payrollAdmin", db_path: Path | None = None) -> dict[str, Any]:
    init_admin_store(db_path)
    now = _now()
    effective_enabled = module_id in OPEN_FOR_RELEASE_MODULE_IDS or (bool(enabled) and module_id not in CLOSED_UNTIL_RELEASE_MODULE_IDS)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            "UPDATE admin_modules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if effective_enabled else 0, now, module_id),
        )
        if cursor.rowcount == 0:
            raise KeyError("module_not_found")
        _insert_audit(connection, actor_user_id, "set_module_enabled", "module", module_id, str(effective_enabled))
        connection.commit()
    return next(module for module in list_modules(db_path) if module["id"] == module_id)


def set_module_role_access(
    module_id: str,
    role_id: str,
    can_enter: bool,
    actor_user_id: str = "payrollAdmin",
    db_path: Path | None = None,
) -> dict[str, Any]:
    init_admin_store(db_path)
    now = _now()
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM admin_modules WHERE id = ?", (module_id,)).fetchone():
            raise KeyError("module_not_found")
        if not connection.execute("SELECT 1 FROM admin_roles WHERE id = ?", (role_id,)).fetchone():
            raise KeyError("role_not_found")
        connection.execute(
            """
            INSERT INTO admin_role_module_permissions (role_id, module_id, can_enter, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(role_id, module_id) DO UPDATE SET
              can_enter = excluded.can_enter,
              updated_at = excluded.updated_at
            """,
            (role_id, module_id, 1 if can_enter else 0, now),
        )
        _insert_audit(connection, actor_user_id, "set_module_role_access", "module_role", f"{module_id}:{role_id}", str(can_enter))
        connection.commit()
    return get_permissions(db_path)["moduleAccess"].get(role_id, {})


def set_feature_permission(
    role_id: str,
    feature_id: str,
    enabled: bool,
    actor_user_id: str = "payrollAdmin",
    db_path: Path | None = None,
) -> dict[str, Any]:
    init_admin_store(db_path)
    now = _now()
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM admin_roles WHERE id = ?", (role_id,)).fetchone():
            raise KeyError("role_not_found")
        connection.execute(
            """
            INSERT INTO admin_role_feature_permissions (role_id, feature_id, enabled, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(role_id, feature_id) DO UPDATE SET
              enabled = excluded.enabled,
              updated_at = excluded.updated_at
            """,
            (role_id, feature_id, 1 if enabled else 0, now),
        )
        _insert_audit(connection, actor_user_id, "set_feature_permission", "role_feature", f"{role_id}:{feature_id}", str(enabled))
        connection.commit()
    return get_permissions(db_path)["rolePermissions"].get(role_id, {})


def count_audit_logs(db_path: Path | None = None) -> int:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM admin_audit_logs WHERE action != ?",
            ("migrate_default_role_module_grant",),
        ).fetchone()
    return int(row["total"] if row else 0)


def list_audit_logs(
    limit: int = 50,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, actor_user_id AS "actorUserId", action, target_type AS "targetType",
                   target_id AS "targetId", detail, created_at AS "createdAt"
            FROM admin_audit_logs
            WHERE action != ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            ("migrate_default_role_module_grant", max(1, limit), max(0, offset)),
        ).fetchall()
    return _rows_to_dicts(rows)


def record_audit_event(
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Persist a server-derived business audit event without request payload data."""
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        _insert_audit(
            connection,
            str(actor_user_id)[:256],
            str(action)[:128],
            str(target_type)[:128],
            str(target_id)[:256],
            str(detail)[:500] if detail is not None else None,
        )
        connection.commit()


def _insert_audit(
    connection: _AdminConnection,
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO admin_audit_logs (actor_user_id, action, target_type, target_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (actor_user_id, action, target_type, target_id, detail, _now()),
    )
