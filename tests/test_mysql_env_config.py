from __future__ import annotations

import importlib


def test_admin_database_url_is_built_from_standard_mysql_environment(monkeypatch):
    from bonus_platform import config

    with monkeypatch.context() as scoped:
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
            scoped.delenv(name, raising=False)

        scoped.setenv("MYSQL_HOST", "mysql.company.internal")
        scoped.setenv("MYSQL_PORT", "3306")
        scoped.setenv("MYSQL_USERNAME", "payroll_app")
        scoped.setenv("MYSQL_DATABASE", "payroll")
        scoped.setenv("MYSQL_PASSWORD", "test-password")

        reloaded = importlib.reload(config)
        assert reloaded.ADMIN_DATABASE_URL == (
            "mysql+pymysql://payroll_app:test-password@mysql.company.internal:3306/payroll"
        )

    importlib.reload(config)
