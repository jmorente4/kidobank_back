from datetime import datetime, timedelta, timezone

from app.models.account import Account, AccountType
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.models.investment import InvestmentProduct
from app.services.market_engine import run_market_updates


class _DownwardShockRandom:
    def random(self):
        return 1.0

    def gauss(self, mean, standard_deviation):
        return -2.0


def test_nino_sin_contrasena_puede_acceder_con_pin_y_tarjeta_qr(client, padre_user):
    login = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    parent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = client.post(
        "/api/v1/users/",
        json={
            "nombre": "Hijo con tarjeta",
            "email": "qr.infantil@kidobank.com",
            "rol": "NINO",
            "codigo_pin": "2468",
            "tarjeta_qr": "QR-TARJETA-2468",
        },
        headers=parent_headers,
    )
    assert created.status_code == 201

    qr_login = client.post(
        "/api/v1/auth/login/pin",
        json={"qr_uuid": "QR-TARJETA-2468", "pin": "2468"},
    )
    assert qr_login.status_code == 200
    assert qr_login.json()["user"]["id"] == created.json()["id"]

    invalid_pin = client.post(
        "/api/v1/auth/login/pin",
        json={"qr_uuid": "QR-TARJETA-2468", "pin": "24680"},
    )
    assert invalid_pin.status_code == 422


def test_flujo_inversion_indice(client, padre_user, db):
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    parent_token = login_res.json()["access_token"]
    parent_headers = {"Authorization": f"Bearer {parent_token}"}

    child = User(
        nombre="Hijo Inversor",
        email="inversor.test@kidobank.com",
        pin_hash=get_password_hash("1234"),
        rol=UserRole.NINO,
        qr_uuid="QR-INV-01",
    )
    db.add(child)
    db.commit()
    db.refresh(child)

    cuenta = Account(
        usuario_id=child.id,
        tipo=AccountType.CORRIENTE,
        saldo=200.0,
        tasa_interes=0.0,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)

    child_login = client.post(
        "/api/v1/auth/login/pin",
        json={"user_id": child.id, "pin": "1234"},
    )
    child_headers = {"Authorization": f"Bearer {child_login.json()['access_token']}"}

    create_product = client.post(
        "/api/v1/investments/products",
        json={
            "nombre": "Índice Tech",
            "codigo": "TECH-01",
            "tipo": "INDICE",
            "descripcion": "Índice temático de tecnología",
            "precio_actual_kidos": 100.0,
            "tasa_rentabilidad": 0.08,
            "duracion_dias": 30,
        },
        headers=parent_headers,
    )
    assert create_product.status_code == 201
    product_id = create_product.json()["id"]

    buy_res = client.post(
        f"/api/v1/investments/products/{product_id}/buy",
        json={"cuenta_id": cuenta.id, "monto_invertido_kidos": 50.0},
        headers=child_headers,
    )
    assert buy_res.status_code == 200
    data = buy_res.json()
    assert data["monto_invertido_kidos"] == 50.0
    assert data["producto_id"] == product_id

    news = client.post(
        "/api/v1/investments/news",
        json={
            "titulo": "Escasez de chips",
            "descripcion": "Aumento de demanda de tecnología",
            "impacto_pct": 8.0,
            "producto_id": product_id,
        },
        headers=parent_headers,
    )
    assert news.status_code == 201
    assert news.json()["precio_resultante"] == 108.0

    final = client.get("/api/v1/investments/products", headers=child_headers)
    assert final.status_code == 200
    assert len(final.json()) >= 1


def test_simulacion_bolsa_y_venta(client, padre_user, db):
    parent_headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login/parent",
            json={"email": "padre.test@kidobank.com", "password": "padre123"},
        ).json()["access_token"]
    }
    child = User(nombre="Vendedor Bolsa", email="bolsa.test@kidobank.com", pin_hash=get_password_hash("1234"), rol=UserRole.NINO)
    db.add(child)
    db.commit()
    db.refresh(child)
    cuenta = Account(usuario_id=child.id, tipo=AccountType.CORRIENTE, saldo=100.0, tasa_interes=0.0)
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    child_headers = {
        "Authorization": "Bearer "
        + client.post("/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "1234"}).json()["access_token"]
    }

    product = client.post(
        "/api/v1/investments/products",
        json={
            "nombre": "Índice Deporte", "codigo": "SPORT-01", "tipo": "INDICE",
            "precio_actual_kidos": 10.0, "tasa_rentabilidad": 0.1, "volatilidad": 0.5,
        },
        headers=parent_headers,
    ).json()
    position = client.post(
        f"/api/v1/investments/products/{product['id']}/buy",
        json={"cuenta_id": cuenta.id, "monto_invertido_kidos": 50.0},
        headers=child_headers,
    ).json()

    product_row = db.get(InvestmentProduct, product["id"])
    product_row.ultima_simulacion = datetime.now(timezone.utc) - timedelta(days=7)
    db.commit()
    assert client.post("/api/v1/investments/simulate", json={}, headers=parent_headers).status_code == 404
    assert run_market_updates(db, now=datetime.now(timezone.utc), rng=_DownwardShockRandom()) == 1
    db.refresh(product_row)
    nuevo_precio = product_row.precio_actual_kidos
    assert nuevo_precio > 0
    cursor = product_row.ultima_simulacion.replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - cursor < timedelta(days=7, seconds=1)

    sell = client.post(
        f"/api/v1/investments/positions/{position['id']}/sell",
        json={"cuenta_id": cuenta.id},
        headers=child_headers,
    )
    assert sell.status_code == 200
    esperado = round(5.0 * nuevo_precio, 2)
    assert sell.json()["monto_recibido_kidos"] == esperado
    db.expire_all()
    assert db.get(Account, cuenta.id).saldo == round(50.0 + esperado, 2)

    again = client.post(
        f"/api/v1/investments/positions/{position['id']}/sell",
        json={"cuenta_id": cuenta.id},
        headers=child_headers,
    )
    assert again.status_code == 400
