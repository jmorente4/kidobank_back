import pytest
from sqlalchemy import create_engine, select, text

from app.core.security import create_access_token, get_password_hash
from app.db.compatibility import ensure_family_columns
from app.models.account import Account
from app.models.user import User, UserRole


def headers(user_id):
    return {"Authorization": f"Bearer {create_access_token(subject=user_id)}"}


def create(client, role, email, auth=None):
    payload = {"nombre": role, "email": email, "rol": role}
    if role in ("PADRE", "MADRE"):
        payload["password"] = "adult123"
    else:
        payload.update(codigo_pin="1234", tarjeta_qr=f"QR-{email}")
    response = client.post("/api/v1/users/", json=payload, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("first,second", [("PADRE", "MADRE"), ("MADRE", "PADRE")])
def test_shared_administrators_and_family_isolation(client, db, first, second):
    root = create(client, first, "root@kidobank.com")
    root_auth = headers(root["id"])
    child = create(client, "NINO", "child@kidobank.com", root_auth)
    other_admin = create(client, second, "shared@kidobank.com", root_auth)
    admin_auth = headers(other_admin["id"])
    relative = create(client, "FAMILIAR", "relative@kidobank.com", admin_auth)
    outsider = create(client, "MADRE", "outsider@kidobank.com")
    outsider_auth = headers(outsider["id"])
    assert root["familia_id"] == root["id"]
    assert other_admin["familia_id"] == child["familia_id"] == relative["familia_id"] == root["id"]
    assert relative["padre_id"] == other_admin["id"]
    assert other_admin["padre_id"] is None
    login = client.post("/api/v1/auth/login/parent", json={
        "email": other_admin["email"], "password": "adult123",
    })
    assert login.status_code == 200
    assert login.json()["user"]["familia_id"] == root["id"]
    for auth in (root_auth, admin_auth):
        visible = client.get("/api/v1/users/", headers=auth)
        assert {u["id"] for u in visible.json()} == {
            root["id"], other_admin["id"], child["id"], relative["id"],
        }
        children = client.get("/api/v1/users/children", headers=auth)
        assert [u["id"] for u in children.json()] == [child["id"]]
        assert client.get(f"/api/v1/accounts/user/{child['id']}", headers=auth).status_code == 200
        assert client.patch(
            f"/api/v1/users/{child['id']}", json={"apellidos": "Compartido"}, headers=auth,
        ).status_code == 200
        assert client.post(
            f"/api/v1/users/{relative['id']}/cards", json={}, headers=auth,
        ).status_code == 201
    for user in (root, other_admin, child, relative):
        assert client.get(f"/api/v1/users/{user['id']}", headers=outsider_auth).status_code == 403
        assert client.get(
            f"/api/v1/accounts/user/{user['id']}", headers=outsider_auth,
        ).status_code == 403
    assert client.post(
        f"/api/v1/users/{child['id']}/unlock", headers=outsider_auth,
    ).status_code == 403
    assert len(db.scalars(select(Account)).all()) == 5


def test_relative_pin_qr_limits_and_restricted_permissions(client):
    mother = create(client, "MADRE", "mother@kidobank.com")
    auth = headers(mother["id"])
    relative = create(client, "FAMILIAR", "relative@kidobank.com", auth)
    child = create(client, "NINO", "child@kidobank.com", auth)
    member_auth = headers(relative["id"])
    for identifier in ({"user_id": relative["id"]}, {"qr_uuid": relative["tarjeta_qr"]}):
        response = client.post("/api/v1/auth/login/pin", json={**identifier, "pin": "1234"})
        assert response.status_code == 200
        assert response.json()["user"]["rol"] == "FAMILIAR"
    assert [u["id"] for u in client.get("/api/v1/users/", headers=member_auth).json()] == [relative["id"]]
    assert client.get(f"/api/v1/users/{child['id']}", headers=member_auth).status_code == 403
    assert client.get(f"/api/v1/accounts/user/{child['id']}", headers=member_auth).status_code == 403
    assert client.post("/api/v1/users/", headers=member_auth, json={
        "nombre": "Intruso", "email": "intruso@kidobank.com", "rol": "MADRE", "password": "adult123",
    }).status_code == 403
    assert client.post(f"/api/v1/users/{relative['id']}/unlock", headers=member_auth).status_code == 403
    for expected in (401, 401, 403):
        assert client.post("/api/v1/auth/login/pin", json={
            "qr_uuid": relative["tarjeta_qr"], "pin": "0000",
        }).status_code == expected
    assert client.get("/api/v1/users/me", headers=member_auth).status_code == 403
    assert client.patch(f"/api/v1/users/{relative['id']}/pin", json={
        "pin_nuevo": "2222",
    }, headers=auth).status_code == 204
    assert client.post("/api/v1/auth/login/pin", json={
        "user_id": relative["id"], "pin": "2222",
    }).status_code == 403
    assert client.post(f"/api/v1/users/{relative['id']}/unlock", headers=auth).status_code == 200
    assert client.post("/api/v1/auth/login/pin", json={
        "user_id": relative["id"], "pin": "2222",
    }).status_code == 200


def test_shared_tasks_bonds_and_relative_rewards(client, db):
    father = create(client, "PADRE", "father@kidobank.com")
    father_auth = headers(father["id"])
    mother = create(client, "MADRE", "mother@kidobank.com", father_auth)
    mother_auth = headers(mother["id"])
    relative = create(client, "FAMILIAR", "relative@kidobank.com", mother_auth)
    relative_auth = headers(relative["id"])
    outsider = create(client, "PADRE", "outsider@kidobank.com")
    outsider_auth = headers(outsider["id"])
    task = client.post("/api/v1/tasks", headers=father_auth, json={
        "usuario_id": relative["id"], "titulo": "Ordenar", "recompensa_kidos": 20,
    })
    assert task.status_code == 201
    task_id = task.json()["id"]
    assert [t["id"] for t in client.get("/api/v1/tasks", headers=mother_auth).json()] == [task_id]
    assert client.get("/api/v1/tasks", headers=outsider_auth).json() == []
    assert client.post(f"/api/v1/tasks/{task_id}/complete", headers=relative_auth).status_code == 200
    account = db.scalar(select(Account).where(Account.usuario_id == relative["id"]))
    assert client.post("/api/v1/transactions/paga", headers=mother_auth, json={
        "cuenta_destino_id": account.id, "monto": 1,
    }).status_code == 201
    assert client.post(f"/api/v1/tasks/{task_id}/approve", headers=outsider_auth, json={
        "cuenta_id": account.id,
    }).status_code == 404
    approved = client.post(f"/api/v1/tasks/{task_id}/approve", headers=mother_auth, json={
        "cuenta_id": account.id,
    })
    assert approved.status_code == 200
    assert approved.json()["aprobada_por_id"] == mother["id"]
    assert client.delete(f"/api/v1/tasks/{task_id}", headers=mother_auth).status_code == 409
    offer = client.post("/api/v1/bonds/offers", headers=father_auth, json={
        "titulo": "Bono familiar", "tasa_interes": 0.05, "plazo_dias": 7, "monto_minimo": 1,
    })
    assert offer.status_code == 201
    offer_id = offer.json()["id"]
    for auth in (mother_auth, relative_auth):
        assert [o["id"] for o in client.get("/api/v1/bonds/offers", headers=auth).json()] == [offer_id]
    assert client.get("/api/v1/bonds/offers", headers=outsider_auth).json() == []
    assert client.delete(f"/api/v1/bonds/offers/{offer_id}", headers=outsider_auth).status_code == 404
    bought = client.post("/api/v1/bonds/", headers=relative_auth, json={
        "oferta_id": offer_id, "cuenta_origen_id": account.id, "monto_invertido": 5,
    })
    assert bought.status_code == 201, bought.text
    assert client.delete(f"/api/v1/bonds/offers/{offer_id}", headers=mother_auth).status_code == 204
    task = client.post("/api/v1/tasks", headers=mother_auth, json={
        "usuario_id": relative["id"], "titulo": "Otra tarea", "recompensa_kidos": 1,
    })
    assert client.delete(f"/api/v1/tasks/{task.json()['id']}", headers=father_auth).status_code == 204


def test_new_admin_can_manage_legacy_children(client, padre_user, db):
    child = User(nombre="Legacy", email="legacy@kidobank.com", rol=UserRole.NINO,
                 padre_id=padre_user.id, pin_hash=get_password_hash("1234"))
    db.add(child)
    db.commit()
    mother = create(client, "MADRE", "mother@kidobank.com", headers(padre_user.id))
    assert client.get(
        f"/api/v1/users/{child.id}", headers=headers(mother["id"]),
    ).status_code == 200


def test_family_backfill_preserves_links_and_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol VARCHAR(20), padre_id INTEGER)"
        ))
        connection.execute(text(
            "INSERT INTO usuarios VALUES (1, 'PADRE', NULL), (2, 'NINO', 1), "
            "(3, 'PADRE', NULL), (4, 'NINO', 3), (5, 'NINO', NULL)"
        ))
    ensure_family_columns(engine)
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT id, familia_id FROM usuarios ORDER BY id"
        )).all() == [(1, 1), (2, 1), (3, 3), (4, 3), (5, 5)]
        connection.execute(text(
            "INSERT INTO usuarios (id, rol, familia_id) VALUES (6, 'MADRE', 1)"
        ))
    ensure_family_columns(engine)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT familia_id FROM usuarios WHERE id = 6"
        )).scalar_one() == 1
    engine.dispose()


def test_mother_password_recovery(client, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    import app.api.v1.endpoints.auth as auth_endpoint

    mother = create(client, "MADRE", "mother@kidobank.com")
    monkeypatch.setattr(auth_endpoint.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(auth_endpoint.settings, "SMTP_FROM_EMAIL", "no-reply@kidobank.com")
    links = []
    monkeypatch.setattr(auth_endpoint, "send_password_reset_email",
                        lambda email, url: links.append(url))
    assert client.post("/api/v1/auth/password/forgot", json={
        "email": mother["email"],
    }).status_code == 202
    assert len(links) == 1
    token = parse_qs(urlsplit(links[0]).query)["token"][0]
    assert client.post("/api/v1/auth/password/reset", json={
        "token": token, "new_password": "newadult123",
    }).status_code == 204
    assert client.post("/api/v1/auth/login/parent", json={
        "email": mother["email"], "password": "newadult123",
    }).status_code == 200
