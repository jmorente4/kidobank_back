from app.core.security import get_password_hash
from app.models.account import Account, AccountType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User, UserRole


def _parent_headers(client):
    response = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_tarea_se_paga_solo_tras_aprobacion_del_adulto(client, padre_user, db):
    parent_headers = _parent_headers(client)
    child = User(
        nombre="Hijo con tarea",
        email="tarea.hijo@kidobank.com",
        pin_hash=get_password_hash("1234"),
        rol=UserRole.NINO,
        padre_id=padre_user.id,
    )
    db.add(child)
    db.commit()
    db.refresh(child)

    account = Account(
        usuario_id=child.id,
        tipo=AccountType.CORRIENTE,
        saldo=10.0,
        tasa_interes=0.0,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    child_login = client.post(
        "/api/v1/auth/login/pin",
        json={"user_id": child.id, "pin": "1234"},
    )
    child_headers = {"Authorization": f"Bearer {child_login.json()['access_token']}"}

    created = client.post(
        "/api/v1/tasks",
        json={
            "usuario_id": child.id,
            "titulo": "Ordenar la habitación",
            "descripcion": "Guardar los juguetes.",
            "recompensa_kidos": 5.0,
        },
        headers=parent_headers,
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["estado"] == "ASIGNADA"
    assert db.get(Account, account.id).saldo == 10.0

    completed = client.post(f"/api/v1/tasks/{task_id}/complete", headers=child_headers)
    assert completed.status_code == 200
    assert completed.json()["estado"] == "PENDIENTE_APROBACION"
    assert db.get(Account, account.id).saldo == 10.0

    approved = client.post(
        f"/api/v1/tasks/{task_id}/approve",
        json={"cuenta_id": account.id},
        headers=parent_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["estado"] == "COMPLETADA"
    assert approved.json()["cuenta_abono_id"] == account.id
    db.refresh(account)
    assert account.saldo == 15.0

    reward_transactions = db.query(Transaction).filter(Transaction.tipo == TransactionType.RECOMPENSA).all()
    assert len(reward_transactions) == 1
    assert reward_transactions[0].cuenta_destino_id == account.id
    assert reward_transactions[0].monto == 5.0

    duplicate_approval = client.post(
        f"/api/v1/tasks/{task_id}/approve",
        json={"cuenta_id": account.id},
        headers=parent_headers,
    )
    assert duplicate_approval.status_code == 400
    db.refresh(account)
    assert account.saldo == 15.0
