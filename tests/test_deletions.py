import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.account import Account, AccountType
from app.models.goal import Goal
from app.models.investment import InvestmentPriceHistory, InvestmentProduct, UserInvestment
from app.models.market import EscrowTransaction, MarketItem, MarketStatus
from app.models.task import Task, TaskStatus
from app.models.transaction import Transaction
from app.models.user import User, UserRole


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


@pytest.fixture
def family(db, padre_user):
    child = User(
        nombre="Delete child", email="delete.child@example.com", rol=UserRole.NINO,
        padre_id=padre_user.id, pin_hash=get_password_hash("1234"),
    )
    outsider = User(
        nombre="Other parent", email="delete.other@example.com", rol=UserRole.PADRE,
        pin_hash=get_password_hash("other123"),
    )
    db.add_all([child, outsider])
    db.flush()
    account = Account(usuario_id=child.id, tipo=AccountType.CORRIENTE, saldo=100)
    db.add(account)
    db.commit()
    return child, outsider, account


@pytest.mark.parametrize("actor", ["child", "parent"])
@pytest.mark.parametrize("saved", [0, 25, 50])
def test_delete_goal_returns_saved_amount_once(client, db, padre_user, family, actor, saved):
    child, outsider, account = family
    headers = _headers(child if actor == "child" else padre_user)
    created = client.post(
        "/api/v1/goals/",
        json={"cuenta_id": account.id, "titulo": "Goal to delete", "monto_objetivo": 50},
        headers=headers,
    )
    assert created.status_code == 201
    goal_id = created.json()["id"]
    if saved:
        assert client.post(
            f"/api/v1/goals/{goal_id}/deposit", json={"monto": saved}, headers=headers
        ).status_code == 200
    url = f"/api/v1/goals/{goal_id}"
    assert client.delete(url, headers=_headers(outsider)).status_code == 403
    assert client.delete(url, headers=headers).status_code == 204
    db.refresh(account)
    assert account.saldo == 100
    assert db.get(Goal, goal_id) is None
    refunds = db.query(Transaction).filter(Transaction.cuenta_destino_id == account.id).all()
    assert len(refunds) == (1 if saved else 0)
    if saved:
        assert refunds[0].monto == saved
    assert client.delete(url, headers=headers).status_code == 404
    db.refresh(account)
    assert account.saldo == 100


def test_deactivate_product_preserves_history_and_allows_sale(client, db, padre_user, family):
    child, _, account = family
    parent_headers = _headers(padre_user)
    child_headers = _headers(child)
    created = client.post(
        "/api/v1/investments/products",
        json={"nombre": "Delete index", "codigo": "DELETE-IDX", "tipo": "INDICE", "precio_actual_kidos": 10},
        headers=parent_headers,
    )
    assert created.status_code == 201
    product_id = created.json()["id"]
    position = client.post(
        f"/api/v1/investments/products/{product_id}/buy",
        json={"cuenta_id": account.id, "monto_invertido_kidos": 20}, headers=child_headers,
    )
    assert position.status_code == 200
    url = f"/api/v1/investments/products/{product_id}"
    assert client.delete(url, headers=child_headers).status_code == 403
    assert client.delete(url, headers=parent_headers).status_code == 204
    assert client.delete(url, headers=parent_headers).status_code == 204
    assert client.get(url, headers=child_headers).json()["activo"] is False
    assert db.get(InvestmentProduct, product_id) is not None
    assert db.query(InvestmentPriceHistory).filter_by(producto_id=product_id).count() == 1
    assert db.get(UserInvestment, position.json()["id"]) is not None
    assert client.get("/api/v1/investments/products", headers=child_headers).json() == []
    assert len(client.get(url + "/history", headers=child_headers).json()) == 1
    assert client.post(
        url + "/buy", json={"cuenta_id": account.id, "monto_invertido_kidos": 10},
        headers=child_headers,
    ).status_code == 400
    assert client.post(
        f"/api/v1/investments/positions/{position.json()['id']}/sell",
        json={"cuenta_id": account.id}, headers=child_headers,
    ).status_code == 200
    db.refresh(account)
    assert account.saldo == 100


def test_retire_item_keeps_previous_escrow(client, db, padre_user, family):
    child, outsider, _ = family
    item = MarketItem(vendedor_id=child.id, titulo="Retire item", precio_kidos=10)
    db.add(item)
    db.flush()
    escrow = EscrowTransaction(
        item_id=item.id, vendedor_id=child.id, comprador_id=padre_user.id,
        monto=10, estado="REEMBOLSADO",
    )
    db.add(escrow)
    db.commit()
    url = f"/api/v1/market/items/{item.id}"
    assert client.delete(url, headers=_headers(outsider)).status_code == 403
    assert client.delete(url, headers=_headers(padre_user)).status_code == 204
    assert client.delete(url, headers=_headers(child)).status_code == 204
    db.refresh(item)
    assert item.estado == MarketStatus.CANCELADO
    assert db.get(EscrowTransaction, escrow.id) is not None
    assert client.get("/api/v1/market/items", headers=_headers(child)).json() == []
    assert len(client.get("/api/v1/market/items?estado=CANCELADO", headers=_headers(child)).json()) == 1
    assert client.post(
        url + "/buy", json={"cuenta_id": 999}, headers=_headers(padre_user)
    ).status_code == 400


@pytest.mark.parametrize("state", [MarketStatus.ESCROW, MarketStatus.VENDIDO])
def test_cannot_retire_committed_item(client, db, padre_user, family, state):
    child, _, _ = family
    item = MarketItem(vendedor_id=child.id, titulo="Committed item", precio_kidos=10, estado=state)
    db.add(item)
    db.commit()
    assert client.delete(
        f"/api/v1/market/items/{item.id}", headers=_headers(child)
    ).status_code == 409
    db.refresh(item)
    assert item.estado == state


@pytest.mark.parametrize("state", list(TaskStatus))
def test_task_delete_only_assigned_by_own_parent(client, db, padre_user, family, state):
    child, outsider, account = family
    task = Task(
        usuario_id=child.id, creado_por_id=padre_user.id, titulo="Delete task",
        recompensa_kidos=5, estado=state,
    )
    db.add(task)
    db.commit()
    url = f"/api/v1/tasks/{task.id}"
    assert client.delete(url, headers=_headers(child)).status_code == 403
    assert client.delete(url, headers=_headers(outsider)).status_code == 404
    response = client.delete(url, headers=_headers(padre_user))
    if state != TaskStatus.ASIGNADA:
        assert response.status_code == 409
        assert db.get(Task, task.id) is not None
    else:
        assert response.status_code == 204
        assert db.get(Task, task.id) is None
        assert client.post(
            url + "/approve", json={"cuenta_id": account.id}, headers=_headers(padre_user)
        ).status_code == 404
    db.refresh(account)
    assert account.saldo == 100


@pytest.mark.parametrize("url", [
    "/api/v1/goals/999",
    "/api/v1/investments/products/999",
    "/api/v1/market/items/999",
    "/api/v1/tasks/999",
])
def test_delete_requires_authentication_and_existing_resource(client, padre_user, url):
    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=_headers(padre_user)).status_code == 404
