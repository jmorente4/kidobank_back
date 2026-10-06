from unittest.mock import MagicMock, patch

from app.db.compatibility import ensure_economy_columns, ensure_family_columns


def test_postgres_market_enum_upgrade_is_idempotent_and_committed():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = []
    connection = engine.begin.return_value.__enter__.return_value
    with patch("app.db.compatibility.inspect", return_value=inspector):
        ensure_economy_columns(engine)
        ensure_economy_columns(engine)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements.count(
        "ALTER TYPE marketstatus ADD VALUE IF NOT EXISTS 'CANCELADO'"
    ) == 2
    assert engine.begin.return_value.__exit__.call_count == 4


def test_non_postgres_does_not_alter_enums():
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    inspector = MagicMock()
    inspector.get_table_names.return_value = []
    with patch("app.db.compatibility.inspect", return_value=inspector):
        ensure_economy_columns(engine)
    engine.begin.return_value.__enter__.return_value.execute.assert_not_called()


def test_new_user_roles_commit_before_family_backfill():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["usuarios"]
    inspector.get_columns.return_value = [
        {"name": name} for name in (
            "id", "rol", "padre_id", "familia_id", "apellidos", "avatar_url", "bloqueado_por_pin",
        )
    ]
    connection = engine.begin.return_value.__enter__.return_value
    with patch("app.db.compatibility.inspect", return_value=inspector):
        ensure_family_columns(engine)
        ensure_family_columns(engine)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements.count("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'MADRE'") == 2
    assert statements.count("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'FAMILIAR'") == 2
    operations = engine.begin.return_value.mock_calls
    enum_end = next(i for i, call in enumerate(operations) if call[0] == "__exit__")
    backfill = next(i for i, call in enumerate(operations) if
                    call[0] == "__enter__().execute" and "UPDATE usuarios" in str(call.args[0]))
    assert enum_end < backfill
