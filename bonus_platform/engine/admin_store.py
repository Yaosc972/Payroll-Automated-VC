from __future__ import annotations

from datetime import datetime
from datetime import timedelta
import hashlib
import re
import sqlite3
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlparse

from .. import config


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
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
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
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
"""


DEFAULT_ROLES = [
    {"id": "admin", "name": "系统管理员", "module_id": None, "is_system": 1},
    {"id": "recruitmentAdmin", "name": "招聘奖金核算管理员", "module_id": "recruitment", "is_system": 0},
    {"id": "employeeAdmin", "name": "国内正式工核算管理员", "module_id": "employee", "is_system": 0},
    {"id": "domesticAdmin", "name": "国内外包工核算管理员", "module_id": "domestic", "is_system": 0},
    {"id": "fbuAdmin", "name": "FBU美洲绩效核算管理员", "module_id": "fbu", "is_system": 0},
    {"id": "overseasAdmin", "name": "海外报账管理员", "module_id": "overseas", "is_system": 0},
]

DEFAULT_USERS = [
    {"id": "payrollAdmin", "name": "Payroll Admin", "email": "payroll.admin@example.com", "role_ids": ["admin"]},
    {"id": "recruitmentAdminUser", "name": "Recruitment Admin", "email": "recruitment.admin@example.com", "role_ids": ["recruitmentAdmin"]},
    {"id": "cnPayrollAdminUser", "name": "CN Payroll Admin", "email": "cn.payroll.admin@example.com", "role_ids": ["employeeAdmin", "domesticAdmin"]},
    {"id": "fbuAdminUser", "name": "FBU Bonus Admin", "email": "fbu.admin@example.com", "role_ids": ["fbuAdmin"]},
    {"id": "overseasAdminUser", "name": "Overseas Audit Admin", "email": "overseas.admin@example.com", "role_ids": ["overseasAdmin"]},
]

DEFAULT_MODULES = [
    {"id": "recruitment", "name": "全球招聘奖金核算", "href": "recruitment.html", "owner_role_id": "recruitmentAdmin", "enabled": 1, "development_status": "available"},
    {"id": "employee", "name": "中国区正式工薪酬核算", "href": "employee-payroll.html", "owner_role_id": "employeeAdmin", "enabled": 0, "development_status": "developing"},
    {"id": "domestic", "name": "中国区外包工薪酬核算", "href": "domestic-labor.html", "owner_role_id": "domesticAdmin", "enabled": 0, "development_status": "developing"},
    {"id": "fbu", "name": "FBU美洲绩效奖金核算", "href": "fbu-performance.html", "owner_role_id": "fbuAdmin", "enabled": 0, "development_status": "developing"},
    {"id": "overseas", "name": "海外劳务报账核对", "href": "overseas-labor.html", "owner_role_id": "overseasAdmin", "enabled": 0, "development_status": "developing"},
]

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
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _expires_at() -> str:
    return (datetime.utcnow().replace(microsecond=0) + timedelta(days=SESSION_TTL_DAYS)).isoformat() + "Z"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _postgres_connection(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Postgres admin store requires installing psycopg[binary]") from exc
    return psycopg.connect(database_url, row_factory=dict_row, prepare_threshold=None)


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
            _seed_defaults(connection)
            connection.commit()
            if db_path is None:
                _STORE_INITIALIZED = True
                _STORE_INITIALIZED_TARGET = target
        except Exception:
            connection.rollback()
            raise
    return get_admin_database_url() if backend == "postgres" else _sqlite_db_path(db_path)


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
    for module in DEFAULT_MODULES:
        _insert_seed(
            connection,
            "admin_modules",
            ["id", "name", "href", "owner_role_id", "enabled", "development_status", "created_at", "updated_at"],
            ["id"],
            {**module, "created_at": now, "updated_at": now},
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
    for role in DEFAULT_ROLES:
        for module in DEFAULT_MODULES:
            can_enter = 1 if role["id"] == "admin" or role.get("module_id") == module["id"] else 0
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


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


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
              WHEN 'fbu' THEN 4 WHEN 'overseas' THEN 5 ELSE 99 END
            """
        ).fetchall()
    return [
        {**dict(row), "enabled": bool(row["enabled"])}
        for row in rows
    ]


def list_users(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        users = _rows_to_dicts(connection.execute(
            'SELECT id, name, email, feishu_open_id AS "feishuOpenId", feishu_union_id AS "feishuUnionId", status FROM admin_users ORDER BY id'
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
            SELECT id, name, email, feishu_open_id AS "feishuOpenId", feishu_union_id AS "feishuUnionId"
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
    ensure_bootstrap_admin_for_user(user_id, db_path)
    state = get_admin_state(db_path)
    user = next((item for item in state["users"] if item["id"] == user_id), None)
    if not user:
        raise KeyError("user_not_found")
    allowed_modules = []
    for module in state["modules"]:
        can_enter = module["enabled"] and any(
            state["moduleAccess"].get(role_id, {}).get(module["id"])
            and state["rolePermissions"].get(role_id, {}).get("enter")
            for role_id in user["roleIds"]
        )
        allowed_modules.append({**module, "canEnter": bool(can_enter)})
    return {
        "user": user,
        "roles": [role for role in state["roles"] if role["id"] in user["roleIds"]],
        "modules": allowed_modules,
        "permissions": {
            "moduleAccess": {role_id: state["moduleAccess"].get(role_id, {}) for role_id in user["roleIds"]},
            "rolePermissions": {role_id: state["rolePermissions"].get(role_id, {}) for role_id in user["roleIds"]},
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
                    feishu_open_id = ?,
                    feishu_union_id = COALESCE(?, feishu_union_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (name, email, feishu_open_id, feishu_union_id, now, user_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO admin_users (
                  id, name, email, feishu_open_id, feishu_union_id, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (user_id, name or email or feishu_open_id, email, feishu_open_id, feishu_union_id, now, now),
            )
        _insert_audit(connection, user_id, "feishu_user_upsert", "user", user_id, email or feishu_open_id)
        connection.commit()
    ensure_bootstrap_admin_for_user(user_id, db_path)
    return next(user for user in list_users(db_path) if user["id"] == user_id)


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


def delete_session(token: str, db_path: Path | None = None) -> None:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_hash_token(token),))
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
    with _connect(db_path) as connection:
        cursor = connection.execute(
            "UPDATE admin_modules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now, module_id),
        )
        if cursor.rowcount == 0:
            raise KeyError("module_not_found")
        _insert_audit(connection, actor_user_id, "set_module_enabled", "module", module_id, str(enabled))
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


def list_audit_logs(limit: int = 50, db_path: Path | None = None) -> list[dict[str, Any]]:
    init_admin_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, actor_user_id AS "actorUserId", action, target_type AS "targetType",
                   target_id AS "targetId", detail, created_at AS "createdAt"
            FROM admin_audit_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return _rows_to_dicts(rows)


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
