import pytest
from app.models.account import Account

# Endpoint correcto según tu router.py
ENDPOINT = "/api/v1/transactions/"


def test_flujo_transferencia_exitosa(client, padre_user, db):
    """
    Verifica una transferencia exitosa entre dos cuentas de niños:
    1. Creación de dos usuarios niños (Origen y Destino) y asignación de saldos.
    2. Realización de una transferencia válida.
    3. Comprobación de que los saldos se actualizan correctamente y se genera la transacción.
    """
    # 1. Obtener Token del Padre
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Registrar Niño 1 (Origen)
    nino1_res = client.post("/api/v1/users/", json={
        "nombre": "Niño Origen", "email": "origen.test@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "1111", "tarjeta_qr": "QR-ORIGEN"
    }, headers=headers)
    nino1_id = nino1_res.json()["id"]

    cuenta1 = db.query(Account).filter(Account.usuario_id == nino1_id).first()
    cuenta1.saldo = 100.0  # 100 Kidos iniciales
    db.commit()
    cuenta1_id = cuenta1.id

    # 3. Registrar Niño 2 (Destino)
    nino2_res = client.post("/api/v1/users/", json={
        "nombre": "Niño Destino", "email": "destino.test@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "2222", "tarjeta_qr": "QR-DESTINO"
    }, headers=headers)
    nino2_id = nino2_res.json()["id"]

    cuenta2 = db.query(Account).filter(Account.usuario_id == nino2_id).first()
    cuenta2.saldo = 20.0  # 20 Kidos iniciales
    db.commit()
    cuenta2_id = cuenta2.id

    # 4. Realizar transferencia de 40 Kidos de Niño 1 a Niño 2
    transfer_data = {
        "cuenta_origen_id": cuenta1_id,
        "cuenta_destino_id": cuenta2_id,
        "monto": 40.0,
        "concepto": "Ahorro conjunto / Regalo"
    }
    response = client.post(ENDPOINT, json=transfer_data, headers=headers)
    assert response.status_code in (200, 201)
    tx_json = response.json()
    assert tx_json["monto"] == 40.0

    # 5. Verificar saldos finales en la base de datos
    db.expire_all()
    assert db.get(Account, cuenta1_id).saldo == 60.0   # 100 - 40
    assert db.get(Account, cuenta2_id).saldo == 60.0   # 20 + 40


def test_transferencia_saldo_insuficiente(client, padre_user, db):
    """
    Verifica que la API rechace con HTTP 400 una transferencia si la cuenta
    de origen no dispone de saldo suficiente.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Registrar usuario con poco saldo
    nino_res = client.post("/api/v1/users/", json={
        "nombre": "Pobre", "email": "pobre.tx@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "3333", "tarjeta_qr": "QR-POBRE"
    }, headers=headers)
    nino_id = nino_res.json()["id"]

    cuenta = db.query(Account).filter(Account.usuario_id == nino_id).first()
    cuenta.saldo = 10.0  # Solo 10 Kidos
    db.commit()

    # Intentar transferir 50 Kidos
    transfer_data = {
        "cuenta_origen_id": cuenta.id,
        "cuenta_destino_id": cuenta.id,
        "monto": 50.0,
        "concepto": "Intento fallido"
    }
    response = client.post(ENDPOINT, json=transfer_data, headers=headers)
    assert response.status_code == 400


def test_transferencia_cuenta_no_encontrada(client, padre_user):
    """
    Verifica que se devuelva HTTP 404 si la cuenta de origen o destino no existe.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    transfer_data = {
        "cuenta_origen_id": 99999,
        "cuenta_destino_id": 88888,
        "monto": 10.0,
        "concepto": "Cuentas fantasma"
    }
    response = client.post(ENDPOINT, json=transfer_data, headers=headers)
    assert response.status_code == 404


def test_listar_transacciones(client, padre_user, db):
    """
    Verifica el listado de transacciones y su filtrado.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(ENDPOINT, headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_abonar_paga_exitosa(client, padre_user, db):
    """
    Verifica que un padre puede abonar con éxito una paga a la cuenta de un niño.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Registrar niño destinatario
    nino_res = client.post("/api/v1/users/", json={
        "nombre": "Niño Paga", "email": "paga.test@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "4444", "tarjeta_qr": "QR-PAGA"
    }, headers=headers)
    nino_id = nino_res.json()["id"]

    cuenta_destino = db.query(Account).filter(Account.usuario_id == nino_id).first()

    # Abonar paga de 25 Kidos
    paga_data = {
        "cuenta_destino_id": cuenta_destino.id,
        "monto": 25.0,
        "concepto": "Paga semanal"
    }
    response = client.post(f"{ENDPOINT}paga", json=paga_data, headers=headers)
    
    assert response.status_code == 201
    data = response.json()
    assert data["monto"] == 25.0
    assert data["tipo"] == "PAGA"


def test_get_my_transactions(client, padre_user, db):
    """
    Verifica que el endpoint /me devuelve el historial de transacciones del usuario autenticado.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"{ENDPOINT}me", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_permisos_historial_cuenta_inexistente(client, padre_user):
    """
    Verifica que consultar el historial de una cuenta que no existe devuelve 404.
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"{ENDPOINT}account/99999", headers=headers)
    assert response.status_code == 404