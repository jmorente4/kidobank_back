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


_DEFAULT_ACCOUNT_NAMES = {"CORRIENTE": "Cuenta corriente", "AHORRO": "Cuenta de ahorro", "INVERSION": "Cuenta de inversión"}


def _ensure_account_names(engine: Engine) -> None:
    """Add cuentas.nombre, name legacy accounts and enforce per-user unique names."""
    if "cuentas" not in inspect(engine).get_table_names():
        return
    _add_missing_columns(engine, "cuentas", {"nombre": "VARCHAR(50)"})
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, usuario_id, tipo, nombre FROM cuentas ORDER BY usuario_id, id")
        ).fetchall()
        used: dict[int, set[str]] = {}
        for row in rows:
            if row.nombre and row.nombre.strip():
                used.setdefault(row.usuario_id, set()).add(row.nombre.strip().lower())
        for row in rows:
            if row.nombre and row.nombre.strip():
                continue
            base = _DEFAULT_ACCOUNT_NAMES.get(str(row.tipo).split(".")[-1], "Cuenta")
            name, n = base, 1
            taken = used.setdefault(row.usuario_id, set())
            while name.lower() in taken:
                n += 1
                name = f"{base} {n}"
            taken.add(name.lower())
            connection.execute(
                text("UPDATE cuentas SET nombre = :nombre WHERE id = :id"), {"nombre": name, "id": row.id}
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_cuentas_usuario_nombre "
                "ON cuentas (usuario_id, lower(nombre))"
            )
        )


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
    _ensure_account_names(engine)
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
            for value in ("INVERSION", "DEPOSITO", "RETIRO", "INTERES", "RECOMPENSA"):
                connection.execute(text(f"ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS '{value}'"))
            connection.execute(text("ALTER TYPE marketstatus ADD VALUE IF NOT EXISTS 'CANCELADO'"))

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
        if "productos_inversion" in tables and "historial_precios_inversion" in tables:
            connection.execute(
                text(
                    "INSERT INTO historial_precios_inversion (producto_id, precio_kidos, fecha) "
                    "SELECT p.id, p.precio_actual_kidos, p.updated_at "
                    "FROM productos_inversion p "
                    "WHERE NOT EXISTS ("
                    "SELECT 1 FROM historial_precios_inversion h WHERE h.producto_id = p.id"
                    ")"
                )
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


def ensure_family_columns(engine: Engine) -> None:
    """Add optional profile fields and populate legacy parent-child links when unambiguous."""
    if "usuarios" not in inspect(engine).get_table_names():
        return
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for role in ("MADRE", "FAMILIAR"):
                connection.execute(text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{role}'"))
    is_new_column = "padre_id" not in {
        column["name"] for column in inspect(engine).get_columns("usuarios")
    }
    _add_missing_columns(
        engine,
        "usuarios",
        {
            "padre_id": "INTEGER",
            "familia_id": "INTEGER",
            "apellidos": "VARCHAR(150)",
            "avatar_url": "VARCHAR(255)",
            "bloqueado_por_pin": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
    )
    with engine.begin() as connection:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_usuarios_padre_id ON usuarios (padre_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_usuarios_familia_id ON usuarios (familia_id)")
        )
        columns = {column["name"] for column in inspect(connection).get_columns("usuarios")}
        if "bloqueado_hasta" in columns:
            connection.execute(
                text(
                    "UPDATE usuarios SET bloqueado_por_pin = TRUE, bloqueado_hasta = NULL "
                    "WHERE rol IN ('NINO', 'FAMILIAR') AND bloqueado_hasta > :now"
                ),
                {"now": datetime.now(timezone.utc).replace(tzinfo=None)},
            )
        if is_new_column:
            parent_ids = connection.execute(
                text("SELECT id FROM usuarios WHERE rol = 'PADRE'")
            ).scalars().all()
            if len(parent_ids) == 1:
                connection.execute(
                    text(
                        "UPDATE usuarios SET padre_id = :parent_id "
                        "WHERE rol = 'NINO' AND padre_id IS NULL"
                    ),
                    {"parent_id": parent_ids[0]},
                )
        connection.execute(text(
            "UPDATE usuarios SET familia_id = id "
            "WHERE rol IN ('PADRE', 'MADRE') AND familia_id IS NULL"
        ))
        connection.execute(text(
            "UPDATE usuarios SET familia_id = ("
            "SELECT COALESCE(p.familia_id, p.id) FROM usuarios p WHERE p.id = usuarios.padre_id"
            ") WHERE familia_id IS NULL AND padre_id IS NOT NULL"
        ))
        connection.execute(text(
            "UPDATE usuarios SET familia_id = id WHERE familia_id IS NULL"
        ))
