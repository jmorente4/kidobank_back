import pytest
from sqlalchemy import create_engine, text

from app.db.compatibility import ensure_family_columns


@pytest.mark.parametrize("role", ["PADRE", "NINO"])
def test_optional_profile_fields_creation_login_update_and_clear(client, padre_user, role):
    parent_login = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    parent_headers = {"Authorization": f"Bearer {parent_login.json()['access_token']}"}
    payload = {
        "nombre": "Alex",
        "apellidos": "Garcia Lopez",
        "avatar_url": "https://example.com/avatar.png",
        "email": "alex.profile@kidobank.com",
        "rol": role,
    }
    if role == "PADRE":
        payload["password"] = "profile123"
        created = client.post("/api/v1/users/", json=payload)
    else:
        payload["codigo_pin"] = "1234"
        created = client.post("/api/v1/users/children", json=payload, headers=parent_headers)
    assert created.status_code == 201
    assert created.json()["apellidos"] == payload["apellidos"]
    assert created.json()["avatar_url"] == payload["avatar_url"]
    user_id = created.json()["id"]

    if role == "PADRE":
        login = client.post(
            "/api/v1/auth/login/parent",
            json={"email": payload["email"], "password": payload["password"]},
        )
    else:
        login = client.post(
            "/api/v1/auth/login/pin", json={"user_id": user_id, "pin": "1234"}
        )
    assert login.status_code == 200
    assert login.json()["user"]["apellidos"] == payload["apellidos"]
    assert login.json()["user"]["avatar_url"] == payload["avatar_url"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    url = f"/api/v1/users/{user_id}"

    unchanged = client.patch(url, json={"nombre": "Alex actualizado"}, headers=headers)
    assert unchanged.status_code == 200
    assert unchanged.json()["apellidos"] == payload["apellidos"]
    assert unchanged.json()["avatar_url"] == payload["avatar_url"]

    updated = client.patch(
        url,
        json={"apellidos": "Lopez", "avatar_url": "https://example.com/new.png"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["apellidos"] == "Lopez"
    assert updated.json()["avatar_url"] == "https://example.com/new.png"
    profile = client.get("/api/v1/users/me", headers=headers)
    assert profile.json()["apellidos"] == "Lopez"
    assert profile.json()["avatar_url"] == "https://example.com/new.png"

    cleared = client.patch(
        url, json={"apellidos": None, "avatar_url": None}, headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["apellidos"] is None
    assert cleared.json()["avatar_url"] is None


def test_existing_profile_without_optional_fields(client, padre_user):
    login = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["apellidos"] is None
    assert response.json()["avatar_url"] is None
    for field, value in (("apellidos", "x" * 151), ("avatar_url", "x" * 256)):
        assert client.patch(
            f"/api/v1/users/{padre_user.id}", json={field: value}, headers=headers
        ).status_code == 422


def test_profile_migration_preserves_existing_data():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol VARCHAR(10), "
                    "padre_id INTEGER, avatar_url VARCHAR(255))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO usuarios (id, rol, avatar_url) "
                    "VALUES (1, 'PADRE', 'https://example.com/existing.png')"
                )
            )
        ensure_family_columns(engine)
        ensure_family_columns(engine)
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT apellidos, avatar_url FROM usuarios WHERE id = 1")
            ).one()
            assert row.apellidos is None
            assert row.avatar_url == "https://example.com/existing.png"
    finally:
        engine.dispose()
