"""Small additive upgrades for databases created before the economy simulator."""
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _add_missing_columns(engine: Engine, table: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    with engine.begin() as connection:
        for name, sql_type in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def ensure_economy_columns(engine: Engine) -> None:
    """Add columns missing from installations where create_all cannot evolve old tables."""
    _add_missing_columns(
        engine,
        "productos_inversion",
        {
            "descripcion": "VARCHAR(500)",
            "precio_base": "FLOAT",
            "volatilidad": "FLOAT NOT NULL DEFAULT 0.03",
            "activo": "BOOLEAN NOT NULL DEFAULT TRUE",
            "ultima_simulacion": "TIMESTAMP",
            "semanas_bajistas_restantes": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "TIMESTAMP",
        },
    )
    _add_missing_columns(
        engine,
        "politicas_inflacion",
        {"tasa_anual": "FLOAT", "tasa_semanal": "FLOAT", "ultima_aplicacion": "TIMESTAMP"},
    )
    _add_missing_columns(engine, "cuentas", {"ultimo_abono_interes": "TIMESTAMP"})
    _add_missing_columns(
        engine,
        "noticias_mercado",
        {
            "producto_id": "INTEGER",
            "precio_anterior": "FLOAT",
            "precio_resultante": "FLOAT",
        },
    )

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'INVERSION'"))

    tables = set(inspect(engine).get_table_names())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as connection:
        if "productos_inversion" in tables:
            product_columns = {
                column["name"] for column in inspect(connection).get_columns("productos_inversion")
            }
            connection.execute(
                text("UPDATE productos_inversion SET precio_base = precio_actual_kidos WHERE precio_base IS NULL")
            )
            if "updated_at" in product_columns:
                connection.execute(
                    text("UPDATE productos_inversion SET updated_at = :now WHERE updated_at IS NULL"),
                    {"now": now},
                )
                connection.execute(
                    text("UPDATE productos_inversion SET ultima_simulacion = updated_at WHERE ultima_simulacion IS NULL")
                )
            else:
                connection.execute(
                    text("UPDATE productos_inversion SET ultima_simulacion = :now WHERE ultima_simulacion IS NULL"),
                    {"now": now},
                )
        if "politicas_inflacion" in tables:
            columns = {column["name"] for column in inspect(connection).get_columns("politicas_inflacion")}
            if "tasa_mensual" in columns:
                rows = connection.execute(
                    text("SELECT id, tasa_mensual FROM politicas_inflacion WHERE tasa_semanal IS NULL")
                ).all()
                for row in rows:
                    weekly_rate = (1 + row.tasa_mensual) ** (12 / 52) - 1
                    connection.execute(
                        text("UPDATE politicas_inflacion SET tasa_semanal = :rate WHERE id = :id"),
                        {"rate": weekly_rate, "id": row.id},
                    )
            if "tasa_anual" in columns:
                rows = connection.execute(
                    text("SELECT id, tasa_anual FROM politicas_inflacion WHERE tasa_semanal IS NULL")
                ).all()
                for row in rows:
                    weekly_rate = (1 + row.tasa_anual) ** (1 / 52) - 1
                    connection.execute(
                        text("UPDATE politicas_inflacion SET tasa_semanal = :rate WHERE id = :id"),
                        {"rate": weekly_rate, "id": row.id},
                    )
            connection.execute(
                text("UPDATE politicas_inflacion SET tasa_semanal = 0 WHERE tasa_semanal IS NULL")
            )
            if "fecha_actualizacion" in columns:
                connection.execute(
                    text("UPDATE politicas_inflacion SET ultima_aplicacion = fecha_actualizacion WHERE ultima_aplicacion IS NULL")
                )
            connection.execute(
                text("UPDATE politicas_inflacion SET ultima_aplicacion = :now WHERE ultima_aplicacion IS NULL"),
                {"now": now},
            )
        if "cuentas" in tables:
            columns = {column["name"] for column in inspect(connection).get_columns("cuentas")}
            if "fecha_creacion" in columns:
                connection.execute(
                    text("UPDATE cuentas SET ultimo_abono_interes = fecha_creacion WHERE ultimo_abono_interes IS NULL")
                )
            connection.execute(
                text("UPDATE cuentas SET ultimo_abono_interes = :now WHERE ultimo_abono_interes IS NULL"),
                {"now": now},
            )
