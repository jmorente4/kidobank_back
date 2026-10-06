from datetime import datetime, timedelta

from app.models.account import Account
from app.models.bond import Bond


def _parent_headers(client):
    res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_child(client, db, headers, email, pin="4321", saldo=200.0):
    res = client.post(
        "/api/v1/users/",
        json={"nombre": "Hijo", "email": email, "password": "password123", "rol": "NINO", "codigo_pin": pin},
        headers=headers,
    )
    assert res.status_code == 201
    child_id = res.json()["id"]
    cuenta = db.query(Account).filter(Account.usuario_id == child_id).first()
    cuenta.saldo = saldo
    db.commit()
    login = client.post("/api/v1/auth/login/pin", json={"user_id": child_id, "pin": pin})
    child_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return child_id, cuenta.id, child_headers


def _create_offer(client, headers, **overrides):
    body = {"titulo": "Bono Familiar", "tasa_interes": 0.10, "plazo_dias": 30, "monto_minimo": 20}
    body.update(overrides)
    return client.post("/api/v1/bonds/offers", json=body, headers=headers)


def test_padre_publica_y_hijo_compra_y_rescata(client, padre_user, db):
    headers = _parent_headers(client)
    child_id, cuenta_id, child_headers = _create_child(client, db, headers, "hijo1@kidobank.com")

    offer = _create_offer(client, headers)
    assert offer.status_code == 201
    offer_id = offer.json()["id"]

    visibles = client.get("/api/v1/bonds/offers", headers=child_headers)
    assert [o["id"] for o in visibles.json()] == [offer_id]

    buy = client.post(
        "/api/v1/bonds/",
        json={"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 100.0},
        headers=child_headers,
    )
    assert buy.status_code == 201
    bono = buy.json()
    assert bono["usuario_id"] == child_id
    assert bono["titulo"] == "Bono Familiar" and bono["tasa_interes"] == 0.10 and bono["plazo_dias"] == 30
    db.expire_all()
    assert db.get(Account, cuenta_id).saldo == 100.0

    assert [b["id"] for b in client.get("/api/v1/bonds/", headers=child_headers).json()] == [bono["id"]]
    assert [b["id"] for b in client.get(f"/api/v1/bonds/?usuario_id={child_id}", headers=headers).json()] == [bono["id"]]

    redeem = client.post(f"/api/v1/bonds/{bono['id']}/redeem", headers=child_headers)
    assert redeem.status_code == 200
    assert redeem.json()["estado"] == "RESCATADO" and redeem.json()["penalizacion_aplicada"] == 10.0
    db.expire_all()
    assert db.get(Account, cuenta_id).saldo == 200.0


def test_vencimiento_bono(client, padre_user, db):
    headers = _parent_headers(client)
    _, cuenta_id, child_headers = _create_child(client, db, headers, "hijo2@kidobank.com")
    offer_id = _create_offer(client, headers).json()["id"]
    bono_id = client.post(
        "/api/v1/bonds/",
        json={"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 100.0},
        headers=child_headers,
    ).json()["id"]

    db.get(Bond, bono_id).fecha_vencimiento = datetime.utcnow() - timedelta(days=1)
    db.commit()

    redeem = client.post(f"/api/v1/bonds/{bono_id}/redeem", headers=child_headers)
    assert redeem.status_code == 200
    assert redeem.json()["estado"] == "COMPLETADO" and redeem.json()["penalizacion_aplicada"] == 0.0
    db.expire_all()
    assert db.get(Account, cuenta_id).saldo == 210.0


def test_el_padre_no_compra_y_solo_el_padre_publica(client, padre_user, db):
    headers = _parent_headers(client)
    _, cuenta_id, child_headers = _create_child(client, db, headers, "hijo3@kidobank.com")
    offer_id = _create_offer(client, headers).json()["id"]

    assert _create_offer(client, child_headers).status_code == 403
    assert client.post("/api/v1/bonds/offers", json={"titulo": "X", "tasa_interes": 0.1, "plazo_dias": 5}).status_code == 401
    assert client.delete(f"/api/v1/bonds/offers/{offer_id}", headers=child_headers).status_code == 403

    buy = client.post(
        "/api/v1/bonds/",
        json={"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 50.0},
        headers=headers,
    )
    assert buy.status_code == 403


def test_validaciones_de_compra(client, padre_user, db):
    headers = _parent_headers(client)
    _, cuenta_id, child_headers = _create_child(client, db, headers, "hijo4@kidobank.com", saldo=10.0)
    _, otra_cuenta, _ = _create_child(client, db, headers, "hijo5@kidobank.com", pin="1111")
    offer_id = _create_offer(client, headers, monto_minimo=5).json()["id"]

    def buy(**kw):
        body = {"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 5.0}
        body.update(kw)
        return client.post("/api/v1/bonds/", json=body, headers=child_headers)

    assert buy(monto_invertido=100.0).status_code == 400  # saldo insuficiente
    assert buy(monto_invertido=1.0).status_code == 400  # por debajo del mínimo
    assert buy(cuenta_origen_id=otra_cuenta).status_code == 403  # cuenta ajena
    assert buy(oferta_id=9999).status_code == 404
    assert buy().status_code == 201


def test_ofertas_aisladas_por_familia_y_retirables(client, padre_user, db):
    headers = _parent_headers(client)
    _, cuenta_id, child_headers = _create_child(client, db, headers, "hijo6@kidobank.com")
    offer_id = _create_offer(client, headers).json()["id"]

    client.post("/api/v1/users/", json={"nombre": "Otro", "email": "otro.bono@kidobank.com", "password": "password123", "rol": "PADRE"})
    r = client.post("/api/v1/auth/login/parent", json={"email": "otro.bono@kidobank.com", "password": "password123"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/bonds/offers", headers=other).json() == []
    assert client.delete(f"/api/v1/bonds/offers/{offer_id}", headers=other).status_code == 404

    assert client.delete(f"/api/v1/bonds/offers/{offer_id}", headers=headers).status_code == 204
    assert client.get("/api/v1/bonds/offers", headers=child_headers).json() == []
    buy = client.post(
        "/api/v1/bonds/",
        json={"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 50.0},
        headers=child_headers,
    )
    assert buy.status_code == 404


def test_patrimonio_de_cuenta_de_inversion(client, padre_user, db):
    from app.models.investment import InvestmentProduct, InvestmentType, UserInvestment

    headers = _parent_headers(client)
    child_id, cuenta_id, child_headers = _create_child(client, db, headers, "hijo7@kidobank.com", saldo=300.0)
    inv = client.post(
        "/api/v1/accounts/", json={"usuario_id": child_id, "nombre": "Mis inversiones", "tipo": "INVERSION", "saldo_inicial": 50},
        headers=headers,
    ).json()
    assert inv["patrimonio_total"] == 50.0 and inv["valor_bonos"] == 0.0

    offer_id = _create_offer(client, headers).json()["id"]
    client.post(
        "/api/v1/bonds/",
        json={"oferta_id": offer_id, "cuenta_origen_id": cuenta_id, "monto_invertido": 100.0},
        headers=child_headers,
    )
    product = InvestmentProduct(
        nombre="Indice", codigo="IDX1", tipo=InvestmentType.INDICE, precio_actual_kidos=12.0, precio_base=10.0
    )
    db.add(product)
    db.flush()
    db.add(UserInvestment(usuario_id=child_id, producto_id=product.id, monto_invertido_kidos=100.0, participaciones=10.0))
    db.commit()

    cuentas = client.get("/api/v1/accounts/me", headers=child_headers).json()
    by_type = {c["tipo"]: c for c in cuentas}
    assert by_type["CORRIENTE"]["patrimonio_total"] is None
    inversion = by_type["INVERSION"]
    assert inversion["valor_inversiones"] == 120.0  # 10 participaciones x 12 Kidos
    assert 100.0 <= inversion["valor_bonos"] < 100.5  # capital + interés devengado hasta ahora
    assert inversion["patrimonio_total"] == round(50.0 + inversion["valor_bonos"] + 120.0, 2)

    detalle = client.get(f"/api/v1/accounts/{inv['id']}", headers=headers).json()
    assert detalle["patrimonio_total"] == inversion["patrimonio_total"]
