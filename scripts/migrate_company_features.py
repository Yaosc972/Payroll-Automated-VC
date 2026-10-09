"""Explicit, idempotent AIDeploy migration; never imported by web startup."""
from pathlib import Path

from bonus_platform import config
from bonus_platform.engine.mysql_db import mysql_connection
from bonus_platform.engine.fbu_performance.migrate_mysql import main as migrate_fbu
from bonus_platform.engine.policy.feed import migrate as migrate_policy


def main():
    if not config.ADMIN_DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeError("Company migrations require MySQL")
    migrate_fbu()
    migrate_policy()
    sql_path = Path(__file__).resolve().parents[1] / "mysql/20261009_china_payroll.sql"
    sql = "\n".join(line for line in sql_path.read_text().splitlines() if not line.lstrip().startswith("--"))
    connection = mysql_connection(config.ADMIN_DATABASE_URL)
    try:
        with connection.cursor() as cursor:
            for statement in sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
