import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.db.compatibility import ensure_family_columns
from app.models.user import User, UserRole


def headers(user_id):
    return {"Authorization": f"Bearer {create_access_token(subject=user_id)}"}


def create_member(client, parent_id, role="NINO", username=" Leo_7 ", email="leo@kidobank.com"):
    return client.post("/api/v1/users/", headers=headers(parent_id), json={
        "nombre": "Leo", "email": email, "rol": role, "codigo_pin": "1234",
        "nombre_usuario": username, "tarjeta_qr": f"QR-{email}",
    })


@pytest.mark.parametrize("role", ["NINO", "FAMILIAR"])
def test_create_and_login_by_username_without_losing_qr(client, padre_user, role):
    response = create_member(client, padre_user.id, role)
    assert response.status_code == 201, response.text
    member = response.json()
    assert member["nombre_usuario"] == "leo_7"
    for identifier in (
        {"nombre_usuario": " LEO_7 "},
        {"user_id": member["id"]},
        {"qr_uuid": member["tarjeta_qr"]},
    ):
        login = client.post("/api/v1/auth/login/pin", json={**identifier, "pin": "1234"})
        assert login.status_code == 200, login.text
        assert login.json()["user"]["id"] == member["id"]
        assert login.json()["user"]["nombre_usuario"] == "leo_7"
    assert client.get("/api/v1/users/me", headers=headers(member["id"])).json()["nombre_usuario"] == "leo_7"


def test_global_case_insensitive_uniqueness_and_atomic_conflicts(client, padre_user, db):
    first = create_member(client, padre_user.id).json()
    other = client.post("/api/v1/users/", json={
        "nombre": "Otra madre", "email": "other@kidobank.com", "rol": "MADRE", "password": "adult123",
    }).json()
    conflict = create_member(client, other["id"], username="LEO_7", email="second@kidobank.com")
    assert conflict.status_code == 409
    assert db.scalar(select(User).where(User.email == "second@kidobank.com")) is None
    second = create_member(client, other["id"], username="otro_7", email="second@kidobank.com").json()
    update = client.patch(f"/api/v1/users/{second['id']}", headers=headers(other["id"]), json={
        "nombre": "No debe guardarse", "nombre_usuario": "LEO_7",
    })
    assert update.status_code == 409
    db.expire_all()
    assert db.get(User, second["id"]).nombre == "Leo"
    assert db.get(User, second["id"]).nombre_usuario == "otro_7"
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE usuarios SET nombre_usuario = 'LEO_7' WHERE id = :id"), {"id": second["id"]})
        db.commit()
    db.rollback()
    assert db.get(User, first["id"]).nombre_usuario == "leo_7"


def test_only_family_administrators_manage_username(client, padre_user):
    member = create_member(client, padre_user.id).json()
    mother = client.post("/api/v1/users/", headers=headers(padre_user.id), json={
        "nombre": "Madre", "email": "mother@kidobank.com", "rol": "MADRE", "password": "adult123",
    }).json()
    outsider = client.post("/api/v1/users/", json={
        "nombre": "Otra madre", "email": "other@kidobank.com", "rol": "MADRE", "password": "adult123",
    }).json()
    url = f"/api/v1/users/{member['id']}"
    assert client.patch(url, headers=headers(member["id"]), json={"nombre_usuario": "otro"}).status_code == 403
    assert client.patch(url, headers=headers(outsider["id"]), json={"nombre_usuario": "otro"}).status_code == 403
    assert client.patch(url, headers=headers(mother["id"]), json={"nombre_usuario": " NUEVO_7 "}).json()["nombre_usuario"] == "nuevo_7"
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": "leo_7", "pin": "1234"}).status_code == 404
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": "nuevo_7", "pin": "1234"}).status_code == 200
    assert client.patch(url, headers=headers(mother["id"]), json={"nombre": "Otro nombre"}).json()["nombre_usuario"] == "nuevo_7"
    assert client.patch(url, headers=headers(mother["id"]), json={"nombre_usuario": None}).json()["nombre_usuario"] is None
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": "nuevo_7", "pin": "1234"}).status_code == 404
    assert client.post("/api/v1/auth/login/pin", json={"user_id": member["id"], "pin": "1234"}).status_code == 200


@pytest.mark.parametrize("role", ["NINO", "FAMILIAR"])
def test_username_qr_and_current_pin_share_permanent_lockout(client, padre_user, db, role):
    member = create_member(client, padre_user.id, role).json()
    member_auth = headers(member["id"])
    assert client.post("/api/v1/auth/login/pin", json={
        "nombre_usuario": "LEO_7", "pin": "0000",
    }).status_code == 401
    assert client.post("/api/v1/auth/login/pin", json={
        "qr_uuid": member["tarjeta_qr"], "pin": "0000",
    }).status_code == 401
    assert client.patch(f"/api/v1/users/{member['id']}/pin", headers=member_auth, json={
        "pin_actual": "0000", "pin_nuevo": "2222",
    }).status_code == 403
    db.refresh(db.get(User, member["id"]))
    assert db.get(User, member["id"]).bloqueado_por_pin
    assert db.get(User, member["id"]).intentos_fallidos == 3
    for identifier in ({"nombre_usuario": "leo_7"}, {"user_id": member["id"]}, {"qr_uuid": member["tarjeta_qr"]}):
        assert client.post("/api/v1/auth/login/pin", json={**identifier, "pin": "1234"}).status_code == 403
    assert client.get("/api/v1/users/me", headers=member_auth).status_code == 403
    parent_auth = headers(padre_user.id)
    assert client.patch(f"/api/v1/users/{member['id']}", headers=parent_auth, json={
        "nombre_usuario": "renamed",
    }).status_code == 200
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": "renamed", "pin": "1234"}).status_code == 403
    assert client.post(f"/api/v1/users/{member['id']}/unlock", headers=parent_auth).status_code == 200
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": "renamed", "pin": "1234"}).status_code == 200


@pytest.mark.parametrize("username", ["ab", "a" * 31, "con espacio", "niño", "leo@", "", "   "])
def test_invalid_usernames_rejected_at_creation_update_and_login(client, padre_user, username):
    assert create_member(client, padre_user.id, username=username).status_code == 422
    member = create_member(client, padre_user.id).json()
    assert client.patch(f"/api/v1/users/{member['id']}", headers=headers(padre_user.id), json={
        "nombre_usuario": username,
    }).status_code == 422
    assert client.post("/api/v1/auth/login/pin", json={"nombre_usuario": username, "pin": "1234"}).status_code == 422


def test_optional_for_legacy_and_not_for_adults_or_ambiguous_login(client, padre_user):
    member = create_member(client, padre_user.id, username=None).json()
    assert member["nombre_usuario"] is None
    assert client.post("/api/v1/auth/login/pin", json={"user_id": member["id"], "pin": "1234"}).status_code == 200
    assert client.post("/api/v1/auth/login/pin", json={"pin": "1234"}).status_code == 400
    for extra in ({"user_id": member["id"]}, {"qr_uuid": member["tarjeta_qr"]}):
        assert client.post("/api/v1/auth/login/pin", json={
            "nombre_usuario": "leo_7", "pin": "1234", **extra,
        }).status_code == 400
    assert client.post("/api/v1/users/", json={
        "nombre": "Madre", "email": "mother@kidobank.com", "rol": "MADRE",
        "password": "adult123", "nombre_usuario": "madre",
    }).status_code == 422
    assert client.patch(f"/api/v1/users/{padre_user.id}", headers=headers(padre_user.id), json={
        "nombre_usuario": "padre",
    }).status_code == 422


@pytest.mark.parametrize("operation", ["create", "update"])
def test_database_conflict_after_availability_check_returns_409(client, padre_user, db, monkeypatch, operation):
    import app.api.v1.endpoints.users as users_endpoint

    first = create_member(client, padre_user.id).json()
    second = create_member(client, padre_user.id, username="other", email="second@kidobank.com").json()
    original_check = users_endpoint._ensure_username_available
    calls = []

    def stale_check(username, session, exclude_user_id=None):
        calls.append(username)
        if len(calls) > 1:
            original_check(username, session, exclude_user_id)

    monkeypatch.setattr(users_endpoint, "_ensure_username_available", stale_check)
    if operation == "create":
        response = create_member(client, padre_user.id, email="third@kidobank.com")
    else:
        response = client.patch(f"/api/v1/users/{second['id']}", headers=headers(padre_user.id), json={
            "nombre_usuario": "leo_7",
        })
    assert response.status_code == 409, response.text
    assert len(calls) == 2
    assert db.get(User, first["id"]).nombre_usuario == "leo_7"
    assert db.get(User, second["id"]).nombre_usuario == "other"
    assert db.scalar(select(User).where(User.email == "third@kidobank.com")) is None


def test_successful_username_login_resets_shared_failures(client, padre_user, db):
    member = create_member(client, padre_user.id).json()
    assert client.post("/api/v1/auth/login/pin", json={
        "user_id": member["id"], "pin": "0000",
    }).status_code == 401
    assert client.post("/api/v1/auth/login/pin", json={
        "nombre_usuario": "LEO_7", "pin": "1234",
    }).status_code == 200
    db.expire_all()
    assert db.get(User, member["id"]).intentos_fallidos == 0


def test_username_migration_is_nullable_idempotent_and_enforces_uniqueness():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol VARCHAR(20))"))
            connection.execute(text("INSERT INTO usuarios VALUES (1, 'PADRE'), (2, 'NINO'), (3, 'NINO')"))
        ensure_family_columns(engine)
        ensure_family_columns(engine)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT nombre_usuario FROM usuarios")).all() == [(None,), (None,), (None,)]
            connection.execute(text("UPDATE usuarios SET nombre_usuario = 'leo_7' WHERE id = 2"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("UPDATE usuarios SET nombre_usuario = 'LEO_7' WHERE id = 3"))
        ensure_family_columns(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT nombre_usuario FROM usuarios WHERE id = 2")).scalar_one() == "leo_7"
    finally:
        engine.dispose()
