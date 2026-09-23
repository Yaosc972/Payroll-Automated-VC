"""Transactional FBU state for company MySQL.

Tables are provisioned by mysql/20260923_fbu_state.sql, never at request time.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from ... import config
from ..mysql_db import mysql_connection


_SAFE_ID = re.compile(r"^[0-9A-Za-z_-]{1,128}$")


def requested() -> bool:
    return os.environ.get("SIGMA_FBU_STATE_BACKEND", "").strip().lower() == "mysql"


def _connection():
    url = str(getattr(config, "ADMIN_DATABASE_URL", "") or "").strip()
    if not url.startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeError("FBU MySQL 状态后端未配置 MySQL 数据库")
    return mysql_connection(url)


def _id(value: str) -> str:
    value = str(value or "").strip()
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("FBU 状态标识无效")
    return value


def _environment() -> str:
    raw = os.environ.get("SIGMA_FBU_STORAGE_ENV") or os.environ.get("SIGMA_LABOR_STORAGE_ENV") or "local"
    return _id(re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_") or "local")


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


def _row(cursor, table: str, run_id: str, *, name: str = "", lock: bool = False):
    # Table names are hard-coded, never derived from request data.
    if table == "sigma_fbu_runs":
        cursor.execute(
            "SELECT core AS data, revision FROM sigma_fbu_runs WHERE environment=%s AND run_id=%s" + (" FOR UPDATE" if lock else ""),
            (_environment(), _id(run_id)),
        )
    elif table == "sigma_fbu_run_sections":
        cursor.execute(
            "SELECT data, revision FROM sigma_fbu_run_sections WHERE environment=%s AND run_id=%s AND section_name=%s" + (" FOR UPDATE" if lock else ""),
            (_environment(), _id(run_id), _id(name)),
        )
    else:
        cursor.execute(
            "SELECT payload AS data, revision FROM sigma_fbu_upload_jobs WHERE environment=%s AND run_id=%s AND job_id=%s" + (" FOR UPDATE" if lock else ""),
            (_environment(), _id(run_id), _id(name)),
        )
    row = cursor.fetchone()
    return {"data": _decode(row["data"]), "revision": int(row["revision"])} if row else None


def load_run_state(run_id: str, sections: set[str]) -> dict[str, Any]:
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            core_row = _row(cursor, "sigma_fbu_runs", run_id)
            if core_row is None:
                return {}
            result = dict(core_row["data"] or {})
            result["__core_revision"] = core_row["revision"]
            revisions: dict[str, int] = {}
            for name in sorted(sections):
                section = _row(cursor, "sigma_fbu_run_sections", run_id, name=name)
                result[name] = section["data"] if section else ([] if name == "results" else {})
                revisions[name] = section["revision"] if section else 0
            result["__section_revisions"] = revisions
            return result
    finally:
        connection.close()


def list_run_states() -> list[dict[str, Any]]:
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT core FROM sigma_fbu_runs WHERE environment=%s", (_environment(),))
            rows = cursor.fetchall()
            return sorted((dict(_decode(row["core"]) or {}) for row in rows),
                          key=lambda row: str(row.get("created_at") or ""), reverse=True)
    finally:
        connection.close()


def load_job(run_id: str, job_id: str) -> dict[str, Any] | None:
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            row = _row(cursor, "sigma_fbu_upload_jobs", run_id, name=job_id)
            return dict(row["data"] or {}) if row else None
    finally:
        connection.close()


def delete_run(run_id: str) -> bool:
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            for table in ("sigma_fbu_upload_jobs", "sigma_fbu_run_sections", "sigma_fbu_runs"):
                cursor.execute(f"DELETE FROM {table} WHERE environment=%s AND run_id=%s", (_environment(), _id(run_id)))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _write(cursor, table: str, run_id: str, data: Any, revision: int, *, name: str = "") -> None:
    encoded = _encode(data)
    if table == "sigma_fbu_runs":
        cursor.execute(
            "INSERT INTO sigma_fbu_runs (environment,run_id,core,revision) VALUES (%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE core=VALUES(core),revision=VALUES(revision)",
            (_environment(), _id(run_id), encoded, revision),
        )
    elif table == "sigma_fbu_run_sections":
        cursor.execute(
            "INSERT INTO sigma_fbu_run_sections (environment,run_id,section_name,data,revision) VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE data=VALUES(data),revision=VALUES(revision)",
            (_environment(), _id(run_id), _id(name), encoded, revision),
        )
    else:
        cursor.execute(
            "INSERT INTO sigma_fbu_upload_jobs (environment,run_id,job_id,payload,revision) VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE payload=VALUES(payload),revision=VALUES(revision)",
            (_environment(), _id(run_id), _id(name), encoded, revision),
        )


def _rpc_once(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _id(payload["p_run_id"])
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            if name == "sigma_fbu_commit_snapshot":
                core = _row(cursor, "sigma_fbu_runs", run_id, lock=True)
                core_revision = core["revision"] if core else 0
                specs = dict(payload.get("p_sections") or {})
                sections = {field: _row(cursor, "sigma_fbu_run_sections", run_id, name=field, lock=True)
                            for field in sorted(specs)}
                conflict = core_revision != int(payload.get("p_expected_core_revision") or 0)
                conflict |= any((sections[field]["revision"] if sections[field] else 0)
                                != int(spec.get("expected_revision") or 0) and not spec.get("replace")
                                for field, spec in specs.items())
                if conflict:
                    connection.rollback()
                    return {"applied": False, "data": core["data"] if core else {}, "revision": core_revision,
                            "sections": {field: {"data": row["data"] if row else None,
                                                  "revision": row["revision"] if row else 0}
                                         for field, row in sections.items()}}
                new_revision = core_revision + 1
                core_data = payload.get("p_core_data") or {}
                _write(cursor, "sigma_fbu_runs", run_id, core_data, new_revision)
                section_results = {}
                for field, spec in specs.items():
                    revision = (sections[field]["revision"] if sections[field] else 0) + 1
                    _write(cursor, "sigma_fbu_run_sections", run_id, spec.get("data"), revision, name=field)
                    section_results[field] = {"data": spec.get("data"), "revision": revision}
                result = {"applied": True, "data": core_data, "revision": new_revision, "sections": section_results}
            elif name in {"sigma_fbu_replace_section", "sigma_fbu_cas_section"}:
                field = _id(payload["p_section_name"])
                row = _row(cursor, "sigma_fbu_run_sections", run_id, name=field, lock=True)
                revision = row["revision"] if row else 0
                if name == "sigma_fbu_cas_section" and revision != int(payload.get("p_expected_revision") or 0):
                    connection.rollback()
                    return {"applied": False, "data": row["data"] if row else None, "revision": revision}
                revision += 1
                _write(cursor, "sigma_fbu_run_sections", run_id, payload.get("p_data"), revision, name=field)
                result = {"applied": True, "data": payload.get("p_data"), "revision": revision}
            elif name in {"sigma_fbu_commit_core", "sigma_fbu_cas_core"}:
                row = _row(cursor, "sigma_fbu_runs", run_id, lock=True)
                revision = row["revision"] if row else 0
                if name == "sigma_fbu_cas_core" and revision != int(payload.get("p_expected_revision") or 0):
                    connection.rollback()
                    return {"applied": False, "data": row["data"] if row else {}, "revision": revision}
                data = payload.get("p_data") if name == "sigma_fbu_cas_core" else {**(row["data"] if row else payload.get("p_seed") or {}), **(payload.get("p_patch") or {})}
                revision += 1
                _write(cursor, "sigma_fbu_runs", run_id, data, revision)
                result = {"applied": True, "data": data, "revision": revision}
            elif name == "sigma_fbu_patch_job":
                job_id = _id(payload["p_job_id"])
                row = _row(cursor, "sigma_fbu_upload_jobs", run_id, name=job_id, lock=True)
                data = dict(row["data"] if row else payload.get("p_seed") or {})
                allowed = payload.get("p_allowed_from")
                if allowed is not None and str(data.get("status") or "") not in allowed:
                    connection.rollback()
                    return {"applied": False, "data": data, "revision": row["revision"] if row else 0}
                data.update(payload.get("p_patch") or {})
                revision = (row["revision"] if row else 0) + 1
                _write(cursor, "sigma_fbu_upload_jobs", run_id, data, revision, name=job_id)
                result = {"applied": True, "data": data, "revision": revision}
            else:
                raise ValueError("不支持的 FBU MySQL 状态操作")
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def rpc(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return _rpc_once(name, payload)
        except Exception as exc:
            code = getattr(exc, "args", (None,))[0]
            if code not in {1062, 1205, 1213} or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("FBU MySQL 状态提交失败")
