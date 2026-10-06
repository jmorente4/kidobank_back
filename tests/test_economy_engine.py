from datetime import datetime, timedelta, timezone

from app.core.security import get_password_hash
from app.models.account import Account, AccountType
from app.models.economy import InflationPolicy, InflationPolicyStatus
from app.models.investment import InvestmentPriceHistory, InvestmentProduct, InvestmentType
from app.models.market import MarketItem, MarketStatus
from app.models.user import User, UserRole
from app.services.market_engine import run_market_updates, run_periodic_jobs, step_price
import random


def _parent_headers(client):
    login = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _child(db, nombre, email, pin):
    user = User(nombre=nombre, email=email, pin_hash=get_password_hash(pin), rol=UserRole.NINO)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_inflacion_se_aplica_una_vez_por_semana(client, padre_user, db):
    now = datetime.now(timezone.utc)
    child = _child(db, "Vendedor semanal", "vend.semanal@kidobank.com", "1111")
    item = MarketItem(
        vendedor_id=child.id,
        titulo="Servicio familiar",
        precio_kidos=100.0,
        estado=MarketStatus.DISPONIBLE,
    )
    policy = InflationPolicy(
        nombre="Inflación familiar",
        tasa_semanal=0.02,
        activa=True,
        estado=InflationPolicyStatus.ACTIVA,
        fecha_actualizacion=now - timedelta(days=7),
        ultima_aplicacion=now - timedelta(days=7),
    )
    db.add_all([item, policy])
    db.commit()

    result = run_periodic_jobs(db, now=now, rng=random.Random(1))
    assert result["semanas_inflacion_aplicadas"] == 1
    db.refresh(item)
    assert item.precio_kidos == 102.0

    result = run_periodic_jobs(db, now=now, rng=random.Random(1))
    assert result["semanas_inflacion_aplicadas"] == 0
    db.refresh(item)
    assert item.precio_kidos == 102.0


def test_inflacion_no_se_aplica_antes_de_una_semana(client, padre_user, db):
    now = datetime.now(timezone.utc)
    child = _child(db, "Vendedor pronto", "vend.pronto@kidobank.com", "1111")
    item = MarketItem(vendedor_id=child.id, titulo="Servicio", precio_kidos=100.0, estado=MarketStatus.DISPONIBLE)
    policy = InflationPolicy(
        nombre="Inflación",
        tasa_semanal=0.02,
        activa=True,
        estado=InflationPolicyStatus.ACTIVA,
        fecha_actualizacion=now,
        ultima_aplicacion=now,
    )
    db.add_all([item, policy])
    db.commit()

    run_periodic_jobs(db, now=now + timedelta(days=6), rng=random.Random(1))
    db.refresh(item)
    assert item.precio_kidos == 100.0


def test_mercado_tiene_semanas_bajistas_consecutivas():
    price = 100.0
    bear_left = 2
    rng = random.Random(17)
    first, bear_left, was_bear = step_price(price, 0.05, 0.04, bear_left, rng)
    assert was_bear
    assert first < price
    assert bear_left == 1

    second, bear_left, was_bear = step_price(first, 0.05, 0.04, bear_left, rng)
    assert was_bear
    assert second < first
    assert bear_left == 0


def test_simulacion_guarda_un_punto_de_historial_por_cada_semana(client, padre_user, db):
    headers = _parent_headers(client)
    created = client.post(
        "/api/v1/investments/products",
        json={
            "nombre": "Indice historico",
            "codigo": "HISTORY-01",
            "tipo": "INDICE",
            "precio_actual_kidos": 100.0,
        },
        headers=headers,
    )
    assert created.status_code == 201
    product = db.get(InvestmentProduct, created.json()["id"])
    initial = db.query(InvestmentPriceHistory).filter_by(producto_id=product.id).one()
    cursor = datetime.now(timezone.utc) - timedelta(days=14)
    product.ultima_simulacion = cursor
    initial.fecha = cursor
    db.commit()

    now = cursor + timedelta(days=14)
    assert run_market_updates(db, now=now, rng=random.Random(7)) == 1
    db.flush()
    points = (
        db.query(InvestmentPriceHistory)
        .filter_by(producto_id=product.id)
        .order_by(InvestmentPriceHistory.fecha.asc())
        .all()
    )
    assert len(points) == 3
    expected_dates = [cursor, cursor + timedelta(days=7), now]
    assert [point.fecha for point in points] == [
        value.replace(tzinfo=None) for value in expected_dates
    ]


def test_noticia_aplica_puntos_porcentuales_y_registra_nuevo_precio(client, padre_user, db):
    headers = _parent_headers(client)
    created = client.post(
        "/api/v1/investments/products",
        json={
            "nombre": "Índice Tecnología",
            "codigo": "TECH-NEWS",
            "tipo": "INDICE",
            "precio_actual_kidos": 100.0,
            "volatilidad": 0.03,
        },
        headers=headers,
    )
    assert created.status_code == 201
    product_id = created.json()["id"]
    product = db.get(InvestmentProduct, product_id)
    product.precio_actual_kidos = 110.0
    product.variacion_pct = 10.0
    db.commit()

    news = client.post(
        "/api/v1/investments/news",
        json={
            "titulo": "Escasez de componentes",
            "descripcion": "La demanda de tecnología baja.",
            "impacto_pct": -5.0,
            "producto_id": product_id,
        },
        headers=headers,
    )
    assert news.status_code == 201
    assert news.json()["precio_anterior"] == 110.0
    assert news.json()["precio_resultante"] == 105.0
    db.refresh(product)
    assert product.precio_actual_kidos == 105.0
    assert product.variacion_pct == 5.0

    history = client.get(f"/api/v1/investments/products/{product_id}/history", headers=headers)
    assert history.status_code == 200
    assert [point["precio_kidos"] for point in history.json()] == [100.0, 105.0]


def test_noticia_global_aplica_a_todos_los_indices_activos(client, padre_user, db):
    headers = _parent_headers(client)
    indices = []
    for name, code, price in (
        ("Índice A", "GLOBAL-A", 100.0),
        ("Índice B", "GLOBAL-B", 200.0),
    ):
        response = client.post(
            "/api/v1/investments/products",
            json={"nombre": name, "codigo": code, "tipo": "INDICE", "precio_actual_kidos": price},
            headers=headers,
        )
        assert response.status_code == 201
        indices.append(response.json())
    bond = client.post(
        "/api/v1/investments/products",
        json={"nombre": "Bono", "codigo": "GLOBAL-BOND", "tipo": "BONO", "precio_actual_kidos": 50.0},
        headers=headers,
    )
    assert bond.status_code == 201

    news = client.post(
        "/api/v1/investments/news",
        json={
            "titulo": "Noticia global",
            "descripcion": "Afecta al mercado de índices.",
            "impacto_pct": 10.0,
        },
        headers=headers,
    )
    assert news.status_code == 201
    assert news.json()["producto_id"] is None
    assert news.json()["precio_anterior"] is None
    assert news.json()["precio_resultante"] is None

    for product, expected in zip(indices, (110.0, 220.0)):
        db.refresh(db.get(InvestmentProduct, product["id"]))
        assert db.get(InvestmentProduct, product["id"]).precio_actual_kidos == expected
        history = client.get(
            f"/api/v1/investments/products/{product['id']}/history",
            headers=headers,
        )
        assert [point["precio_kidos"] for point in history.json()] == [product["precio_actual_kidos"], expected]
    assert db.get(InvestmentProduct, bond.json()["id"]).precio_actual_kidos == 50.0


def test_interes_de_ahorro_se_paga_semanalmente_y_es_idempotente(client, padre_user, db):
    now = datetime.now(timezone.utc)
    child = _child(db, "Ahorrador", "ahorra.semanal@kidobank.com", "1111")
    account = Account(
        usuario_id=child.id,
        tipo=AccountType.AHORRO,
        saldo=100.0,
        tasa_interes=0.02,
        ultimo_abono_interes=now - timedelta(days=7),
    )
    db.add(account)
    db.commit()

    run_periodic_jobs(db, now=now, rng=random.Random(1))
    db.refresh(account)
    assert account.saldo == 102.0

    run_periodic_jobs(db, now=now, rng=random.Random(1))
    db.refresh(account)
    assert account.saldo == 102.0
