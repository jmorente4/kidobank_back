from app.core.security import get_password_hash
from app.models.account import Account, AccountType
from app.models.user import User, UserRole


def _create_child_with_account(db, name, email, pin, saldo=100.0):
    user = User(
        nombre=name,
        email=email,
        pin_hash=get_password_hash(pin),
        rol=UserRole.NINO,
        qr_uuid=f"QR-{name.lower().replace(' ', '-')}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    account = Account(
        usuario_id=user.id,
        tipo=AccountType.CORRIENTE,
        saldo=saldo,
        tasa_interes=0.0,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return user, account


def test_mercadillo_compra_con_escrow(client, db):
    seller_user, seller_account = _create_child_with_account(db, "Vendedor", "vendedor@kidobank.com", "1111", saldo=100.0)
    buyer_user, buyer_account = _create_child_with_account(db, "Comprador", "comprador@kidobank.com", "2222", saldo=100.0)

    seller_login = client.post("/api/v1/auth/login/pin", json={"user_id": seller_user.id, "pin": "1111"})
    seller_headers = {"Authorization": f"Bearer {seller_login.json()['access_token']}"}

    buyer_login = client.post("/api/v1/auth/login/pin", json={"user_id": buyer_user.id, "pin": "2222"})
    buyer_headers = {"Authorization": f"Bearer {buyer_login.json()['access_token']}"}

    create_item = client.post(
        "/api/v1/market/items",
        json={"titulo": "Bicicleta de juguete", "descripcion": "Pequeña bicicleta de madera", "precio_kidos": 40.0},
        headers=seller_headers,
    )
    assert create_item.status_code == 201
    item_id = create_item.json()["id"]

    purchase = client.post(
        f"/api/v1/market/items/{item_id}/buy",
        json={"cuenta_id": buyer_account.id},
        headers=buyer_headers,
    )
    assert purchase.status_code == 200
    assert purchase.json()["estado"] == "PENDIENTE"

    db.expire_all()
    assert db.get(Account, buyer_account.id).saldo == 60.0

    confirm = client.post(f"/api/v1/market/items/{item_id}/confirm-delivery", headers=buyer_headers)
    assert confirm.status_code == 200
    assert confirm.json()["estado"] == "CONFIRMADO"

    db.expire_all()
    assert db.get(Account, buyer_account.id).saldo == 60.0
    assert db.get(Account, seller_account.id).saldo == 140.0
