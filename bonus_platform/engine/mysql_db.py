"""Small MySQL connection helper used by local and company-server modes.

The application keeps database URLs in environment variables so the local
single-machine profile and the company-server profile can share the same
business code.  This module deliberately keeps the connection surface small:
callers receive a DB-API connection with dictionary rows and a fixed business
timezone for deterministic payroll dates.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


_TIME_ZONE_RE = re.compile(r"^(?:SYSTEM|[+-](?:0\d|1[0-4]):[0-5]\d)$")


def mysql_connection(database_url: str) -> Any:
    """Open a MySQL connection from a ``mysql://`` style URL.

    PyMySQL is imported lazily so SQLite-only local tests do not require a
    running MySQL server.  Passwords and connection URLs are never included in
    raised error messages by this helper.
    """

    try:
        import pymysql
    except ImportError as exc:  # pragma: no cover - exercised in setup errors
        raise RuntimeError("MySQL 模式需要安装 PyMySQL。") from exc

    parsed = urlparse(str(database_url or ""))
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise RuntimeError("MySQL 数据库地址必须使用 mysql:// 或 mysql+pymysql://。")
    if not parsed.hostname:
        raise RuntimeError("MySQL 数据库地址缺少主机名。")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise RuntimeError("MySQL 数据库地址缺少数据库名。")

    query = parse_qs(parsed.query, keep_blank_values=True)
    charset = str(query.get("charset", ["utf8mb4"])[0] or "utf8mb4")
    time_zone = str(
        os.environ.get("SIGMA_MYSQL_TIME_ZONE")
        or query.get("time_zone", ["+08:00"])[0]
        or "+08:00"
    ).strip()
    if not _TIME_ZONE_RE.fullmatch(time_zone):
        raise RuntimeError("SIGMA_MYSQL_TIME_ZONE 格式无效。")

    connection = pymysql.connect(
        host=parsed.hostname,
        port=int(parsed.port or 3306),
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=database,
        charset=charset,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=30,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET time_zone=%s", (time_zone,))
    return connection
