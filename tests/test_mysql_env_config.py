from __future__ import annotations

import importlib


def test_admin_database_url_is_built_from_standard_mysql_environment(monkeypatch):
    from bonus_platform import config

    for name in (
        "ADMIN_DATABASE_URL",
        "MYSQL_URL",
        "DATABASE_URL",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USERNAME",
        "MYSQL_USER",
        "MYSQL_DATABASE",
        "MYSQL_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("MYSQL_HOST", "mysql.company.internal")
    monkeypatch.setenv("MYSQL_PORT", "3306")
    monkeypatch.setenv("MYSQL_USERNAME", "payroll_app")
    monkeypatch.setenv("MYSQL_DATABASE", "payroll")
    monkeypatch.setenv("MYSQL_PASSWORD", "test-password")

    reloaded = importlib.reload(config)

    try:
        assert reloaded.ADMIN_DATABASE_URL == (
            "mysql+pymysql://payroll_app:test-password@mysql.company.internal:3306/payroll"
        )
    finally:
        importlib.reload(config)
