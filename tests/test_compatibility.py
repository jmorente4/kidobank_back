from unittest.mock import MagicMock, patch

from app.db.compatibility import ensure_economy_columns


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
