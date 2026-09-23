"""Idempotent FBU MySQL schema migration for AIDeploy's migration gate."""

from __future__ import annotations

from pathlib import Path

from ... import config
from ..mysql_db import mysql_connection


def main() -> None:
    database_url = str(getattr(config, "ADMIN_DATABASE_URL", "") or "").strip()
    if not database_url.startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeError("FBU 表迁移需要 MySQL 数据库连接")
    sql_path = Path(__file__).resolve().parents[3] / "mysql" / "20260923_fbu_state.sql"
    statements = "\n".join(
        line for line in sql_path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).split(";")
    connection = mysql_connection(database_url)
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                if statement.strip():
                    cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
