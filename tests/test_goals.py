import pytest
from app.models.account import Account
from app.models.goal import Goal  # Asegúrate de que tu modelo se importe desde aquí o ajústalo según tu estructura


def test_flujo_completo_metas_ahorro(client, padre_user, db):
    """
    Verifica el ciclo de vida completo de una Meta de Ahorro:
    1. Creación de un usuario niño y asignación de saldo inicial.
    2. Creación de una meta de ahorro (ej. Comprar una bicicleta).
    3. Realizar una aportación a la meta (descuenta saldo de la cuenta y aumenta el progreso).
    4. Verificar el estado y los fondos acumulados.
    """
    # 1. Obtener Token del Padre
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Registrar al Niño para la meta
    nino_data = {
        "nombre": "Ahorrador Test",
        "email": "ahorrador.test@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "1234",
        "tarjeta_qr": "QR-AHORRO-01",
    }
    create_res = client.post("/api/v1/users/", json=nino_data, headers=headers)
    assert create_res.status_code == 201
    nino_id = create_res.json()["id"]

    # 3. Asignar saldo inicial a la cuenta del niño
    cuenta_nino = db.query(Account).filter(Account.usuario_id == nino_id).first()
    assert cuenta_nino is not None
    cuenta_nino.saldo = 150.0  # 150 Kidos disponibles
    db.commit()
    cuenta_id = cuenta_nino.id

    # 4. Crear una Meta de Ahorro
    goal_data = {
        "cuenta_id": cuenta_id,
        "titulo": "Bicicleta Nueva",
        "monto_objetivo": 100.0,
        "icono": "bicycle",
    }
    goal_res = client.post("/api/v1/goals/", json=goal_data, headers=headers)
    print(f"\nSTATUS CODE GOAL: {goal_res.status_code}")
    print(f"RESPONSE BODY GOAL: {goal_res.text}")
    
    # Si tus rutas de metas tienen otro prefijo (ej: /api/v1/savings-goals/), ajústalo aquí.
    assert goal_res.status_code == 201
    goal_json = goal_res.json()
    goal_id = goal_json["id"]
    assert goal_json["titulo"] == "Bicicleta Nueva"
    assert goal_json["monto_objetivo"] == 100.0
    assert goal_json["monto_actual"] == 0.0

    # 5. Realizar una aportación a la meta (ej. 40 Kidos)
    aportacion_data = {
        "monto": 40.0
    }
    deposit_res = client.post(f"/api/v1/goals/{goal_id}/deposit", json=aportacion_data, headers=headers)
    assert deposit_res.status_code == 200
    deposit_json = deposit_res.json()
    assert deposit_json["monto_actual"] == 40.0

    # 6. Comprobar que el saldo de la cuenta del niño disminuyó (150 - 40 = 110)
    db.expire_all()
    cuenta_actualizada = db.get(Account, cuenta_id)
    assert cuenta_actualizada.saldo == 110.0