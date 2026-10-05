from datetime import datetime, timedelta, timezone
from app.models.account import Account
from app.models.bond import Bond, BondStatus


def test_flujo_completo_bonos(client, padre_user, db):
    """
    Verifica el flujo completo de renta fija utilizando la fixture 'db' de pytest:
    1. Obtención de token de padre y creación de un usuario niño.
    2. Asignación de saldo inicial a la cuenta del niño.
    3. Compra de un bono de renta fija (descuento de saldo).
    4. Rescate anticipado del bono (comprobación de penalización y devolución de principal).
    """
    # 1. Obtener Token del Padre
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Registrar al Niño
    nino_data = {
        "nombre": "Inversor Test",
        "email": "inversor.test@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "4321",
        "tarjeta_qr": "QR-INVERSOR-55",
    }
    create_res = client.post("/api/v1/users/", json=nino_data, headers=headers)

    print(f"\nSTATUS CODE: {create_res.status_code}")
    print(f"RESPONSE BODY: {create_res.text}")

    assert create_res.status_code == 201
    nino_id = create_res.json()["id"]

    # 3. Asignar saldo inicial a la cuenta corriente del niño usando la sesión 'db'
    cuenta_nino = db.query(Account).filter(Account.usuario_id == nino_id).first()
    assert cuenta_nino is not None
    cuenta_nino.saldo = 200.0  # Damos 200 Kidos para invertir
    db.commit()
    cuenta_id = cuenta_nino.id

    # 4. Comprar un Bono de Renta Fija
    bond_data = {
        "cuenta_origen_id": cuenta_id,
        "titulo": "Bono Tecnológico Familiar",
        "monto_invertido": 100.0,
        "plazo_dias": 30,
        "tasa_interes": 0.10,  # 10% de interés
    }
    buy_res = client.post("/api/v1/bonds/", json=bond_data, headers=headers)
    print(f"\nSTATUS CODE BOND: {buy_res.status_code}")
    print(f"RESPONSE BODY BOND: {buy_res.text}")
    assert buy_res.status_code == 201

    bond_id = buy_res.json()["id"]

    bono_json = buy_res.json()
    assert bono_json["monto_invertido"] == 100.0
    assert bono_json["estado"] == "ACTIVO"
    
    # Comprobar que el saldo de la cuenta se redujo a 100.0 Kidos
    db.expire_all()
    cuenta_actualizada = db.get(Account, cuenta_id)
    assert cuenta_actualizada.saldo == 100.0

    # 5. Listar los bonos del usuario
    list_res = client.get(f"/api/v1/bonds/?usuario_id={nino_id}", headers=headers)
    assert list_res.status_code == 200
    bonos_list = list_res.json()
    assert len(bonos_list) == 1
    assert bonos_list[0]["id"] == bond_id

    # 6. Intentar rescate anticipado (debe penalizar y devolver solo el principal sin intereses)
    redeem_res = client.post(f"/api/v1/bonds/{bond_id}/redeem", headers=headers)
    assert redeem_res.status_code == 200
    redeemed_json = redeem_res.json()
    assert redeemed_json["estado"] == "RESCATADO"
    assert redeemed_json["penalizacion_aplicada"] == 10.0  # 10% de 100 Kidos perdido

    # Comprobar que el saldo de la cuenta vuelve a ser 200.0 (se devolvió el principal)
    db.expire_all()
    cuenta_tras_rescate = db.get(Account, cuenta_id)
    assert cuenta_tras_rescate.saldo ==  200.0


def test_vencimiento_bono(client, padre_user, db):
    """
    Verifica el flujo cuando un bono llega a su fecha de vencimiento:
    1. Compra de un bono.
    2. Simulación de paso del tiempo (retrocediendo la fecha de vencimiento en la BD).
    3. Rescate exitoso (estado COMPLETADO, sin penalización, devolución de principal + intereses).
    """
    # 1. Obtener Token del Padre y crear niño con saldo
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    nino_data = {
        "nombre": "Inversor Vencimiento",
        "email": "vencimiento.test@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "4321",
        "tarjeta_qr": "QR-VENC-99",
    }
    create_res = client.post("/api/v1/users/", json=nino_data, headers=headers)
    nino_id = create_res.json()["id"]

    cuenta_nino = db.query(Account).filter(Account.usuario_id == nino_id).first()
    cuenta_nino.saldo = 200.0
    db.commit()
    cuenta_id = cuenta_nino.id

    # 2. Comprar un Bono de Renta Fija (100 Kidos al 10% de interés)
    bond_data = {
        "cuenta_origen_id": cuenta_id,
        "titulo": "Bono a Vencimiento",
        "monto_invertido": 100.0,
        "plazo_dias": 30,
        "tasa_interes": 0.10,
    }
    buy_res = client.post("/api/v1/bonds/", json=bond_data, headers=headers)
    assert buy_res.status_code == 201
    bond_id = buy_res.json()["id"]

    # 3. Simular que el tiempo ha pasado: forzar fecha_vencimiento al pasado
    bono = db.get(Bond, bond_id)
    bono.fecha_vencimiento = datetime.utcnow() - timedelta(days=1)
    db.commit()

    # 4. Rescatar el bono vencido
    redeem_res = client.post(f"/api/v1/bonds/{bond_id}/redeem", headers=headers)
    assert redeem_res.status_code == 200
    redeemed_json = redeem_res.json()
    
    # Comprobaciones de éxito y sin penalización
    assert redeemed_json["estado"] == "COMPLETADO"
    assert redeemed_json["penalizacion_aplicada"] == 0.0

    # 5. Comprobar saldo final:
    # Saldo inicial (200) - inversión (100) + devolución (principal 100 + 10% interés = 110) = 210.0
    db.expire_all()
    cuenta_tras_vencimiento = db.get(Account, cuenta_id)
    assert cuenta_tras_vencimiento.saldo == 210.0

def test_compra_bono_saldo_insuficiente(client, padre_user, db):
    """
    Verifica que no se pueda comprar un bono si la cuenta no tiene suficiente saldo (HTTP 400).
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    nino_data = {
        "nombre": "Inversor Pobre",
        "email": "pobre.test@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "4321",
        "tarjeta_qr": "QR-POBRE-01",
    }
    create_res = client.post("/api/v1/users/", json=nino_data, headers=headers)
    nino_id = create_res.json()["id"]

    cuenta_nino = db.query(Account).filter(Account.usuario_id == nino_id).first()
    cuenta_nino.saldo = 10.0  # Solo 10 Kidos
    db.commit()
    cuenta_id = cuenta_nino.id

    bond_data = {
        "cuenta_origen_id": cuenta_id,
        "titulo": "Bono Caro",
        "monto_invertido": 100.0,  # Intentamos invertir 100 con solo 10 en cuenta
        "plazo_dias": 30,
        "tasa_interes": 0.10,
    }
    buy_res = client.post("/api/v1/bonds/", json=bond_data, headers=headers)
    assert buy_res.status_code == 400
    assert "Saldo insuficiente" in buy_res.json()["detail"]


def test_redeem_bono_ajeno_forbidden(client, padre_user, db):
    """
    Verifica que un niño no pueda rescatar o gestionar el bono de otro usuario (HTTP 403).
    """
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Crear Niño 1 (Propietario del bono)
    nino1_res = client.post("/api/v1/users/", json={
        "nombre": "Niño Uno", "email": "nino1.test@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "1111", "tarjeta_qr": "QR-N1"
    }, headers=headers)
    nino1_id = nino1_res.json()["id"]

    cuenta1 = db.query(Account).filter(Account.usuario_id == nino1_id).first()
    cuenta1.saldo = 100.0
    db.commit()

    # Niño 1 compra su bono
    buy_res = client.post("/api/v1/bonds/", json={
        "cuenta_origen_id": cuenta1.id, "titulo": "Bono Niño 1",
        "monto_invertido": 50.0, "plazo_dias": 30, "tasa_interes": 0.05
    }, headers=headers)
    bond_id = buy_res.json()["id"]

    # Crear Niño 2 (Intruso)
    nino2_res = client.post("/api/v1/users/", json={
        "nombre": "Niño Dos", "email": "nino2.test@kidobank.com",
        "password": "pwd123", "rol": "NINO", "codigo_pin": "2222", "tarjeta_qr": "QR-N2"
    }, headers=headers)

    # Login como Niño 2
    login_nino2 = client.post("/api/v1/auth/login/parent", json={"email": "nino2.test@kidobank.com", "password": "pwd123"}) # Nota: Si el login de niño usa otra ruta o requiere token de niño, ajustarlo según tu auth.
    # Alternativa: generar token para el niño 2 directamente con su endpoint de login de niño si existe, o usar el token del padre pero simulando rol. 
    # Supongamos que tenemos login para niños o usamos el token de padre (el padre SÍ puede, pero probaremos con el token del niño 2 si hay endpoint de login de niño).