from bonus_platform.engine import admin_store, local_store


def test_mysql_schemas_use_collation_supported_by_company_mysql():
    schemas = (admin_store.MYSQL_SCHEMA, local_store.MYSQL_SCHEMA)

    for schema in schemas:
        assert "utf8mb4_0900_ai_ci" not in schema
        assert "utf8mb4_unicode_ci" in schema

