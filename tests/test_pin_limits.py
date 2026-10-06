from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.dialects import postgresql

from app.core.security import create_access_token, get_password_hash
from app.models.qr_card import QrCard
from app.models.user import User, UserRole
from app.services.login_attempts import lock_auth_user
from app.db.compatibility import ensure_family_columns


@pytest.fixture
def child(db, padre_user):
    user = User(
        nombre="PIN child",
        email="pin.limit@kidobank.com",
        rol=UserRole.NINO,
        padre_id=padre_user.id,
        pin_hash=get_password_hash("1234"),
        qr_uuid="PIN-LEGACY",
    )
    db.add(user)
    db.flush()
    db.add(QrCard(usuario_id=user.id, qr_uuid="PIN-CARD", activa=True))
    db.commit()
    return user


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


def test_pin_budget_shared_by_id_and_all_qr_cards(client, child, db):
    for identifier, expected in (
        ({"user_id": child.id}, 401),
        ({"qr_uuid": "PIN-LEGACY"}, 401),
        ({"qr_uuid": "PIN-CARD"}, 403),
    ):
        response = client.post("/api/v1/auth/login/pin", json={**identifier, "pin": "0000"})
        assert response.status_code == expected
    db.refresh(child)
    assert child.intentos_fallidos == 3
    assert child.bloqueado_por_pin is True
    assert child.bloqueado_hasta is None
    blocked_until = child.bloqueado_hasta
    with patch("app.api.v1.endpoints.auth.verify_pin") as verify:
        blocked = client.post(
            "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "1234"}
        )
        assert blocked.status_code == 403
        assert "Retry-After" not in blocked.headers
        verify.assert_not_called()
    db.refresh(child)
    assert child.intentos_fallidos == 3
    assert child.bloqueado_hasta == blocked_until


def test_current_pin_failures_share_login_budget(client, child, db):
    headers = _headers(child)
    url = f"/api/v1/users/{child.id}/pin"
    assert client.post(
        "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "0000"}
    ).status_code == 401
    for _ in range(2):
        assert client.patch(
            url, json={"pin_actual": "0000", "pin_nuevo": "2222"}, headers=headers
        ).status_code == 403
    db.refresh(child)
    assert child.intentos_fallidos == 3
    assert child.bloqueado_por_pin is True
    assert client.patch(
        url, json={"pin_actual": "1234", "pin_nuevo": "2222"}, headers=headers
    ).status_code == 403
    assert client.get("/api/v1/users/me", headers=headers).status_code == 403


def test_child_lockout_does_not_expire(client, child, db):
    child.intentos_fallidos = 3
    child.bloqueado_por_pin = True
    child.bloqueado_hasta = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    response = client.post(
        "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "0000"}
    )
    assert response.status_code == 403
    db.refresh(child)
    assert child.intentos_fallidos == 3
    assert client.post(
        "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "1234"}
    ).status_code == 403
    db.refresh(child)
    assert child.intentos_fallidos == 3


def test_parent_must_explicitly_unlock_child(client, child, padre_user, db):
    child.intentos_fallidos = 3
    child.bloqueado_por_pin = True
    db.commit()
    children = client.get("/api/v1/users/children", headers=_headers(padre_user))
    assert children.status_code == 200
    assert children.json()[0]["bloqueado_por_pin"] is True
    assert client.patch(
        f"/api/v1/users/{child.id}/pin",
        json={"pin_nuevo": "2222"},
        headers=_headers(padre_user),
    ).status_code == 204
    assert client.post(
        "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "2222"}
    ).status_code == 403
    unlocked = client.post(
        f"/api/v1/users/{child.id}/unlock", headers=_headers(padre_user)
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["bloqueado_por_pin"] is False
    db.refresh(child)
    assert child.intentos_fallidos == 0
    assert client.post(
        "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "2222"}
    ).status_code == 200


def test_only_own_parent_can_unlock(client, child, db):
    outsider = User(
        nombre="Other parent", rol=UserRole.PADRE,
        email="other.unlock@kidobank.com", pin_hash=get_password_hash("other123"),
    )
    db.add(outsider)
    db.commit()
    url = f"/api/v1/users/{child.id}/unlock"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=_headers(child)).status_code == 403
    assert client.post(url, headers=_headers(outsider)).status_code == 403


def test_adult_lockout_remains_temporary(client, padre_user, db):
    padre_user.intentos_fallidos = 3
    padre_user.bloqueado_hasta = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    response = client.post(
        "/api/v1/auth/login/parent",
        json={"email": padre_user.email, "password": "wrong123"},
    )
    assert response.status_code == 401
    db.refresh(padre_user)
    assert padre_user.intentos_fallidos == 1
    assert padre_user.bloqueado_hasta is None


def test_migration_converts_active_child_lockouts():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol VARCHAR(10), "
                "padre_id INTEGER, bloqueado_hasta TIMESTAMP)"
            ))
            connection.execute(
                text("INSERT INTO usuarios (id, rol, bloqueado_hasta) VALUES "
                     "(1, 'NINO', :until), (2, 'PADRE', :until)"),
                {"until": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)},
            )
        ensure_family_columns(engine)
        ensure_family_columns(engine)
        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT bloqueado_por_pin, bloqueado_hasta FROM usuarios ORDER BY id"
            )).all()
            assert rows[0].bloqueado_por_pin
            assert rows[0].bloqueado_hasta is None
            assert not rows[1].bloqueado_por_pin
            assert rows[1].bloqueado_hasta is not None
    finally:
        engine.dispose()


def test_lock_refreshes_stale_authentication_object(child, db):
    db.execute(
        update(User)
        .where(User.id == child.id)
        .values(intentos_fallidos=2)
        .execution_options(synchronize_session=False)
    )
    assert child.intentos_fallidos == 0
    locked = lock_auth_user(db, child.id)
    assert locked is child
    assert locked.intentos_fallidos == 2


def test_pin_verification_uses_postgresql_row_lock(client, child, db):
    locked_queries = []

    def capture_lock(execute_state):
        statement = execute_state.statement
        if execute_state.is_select:
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                locked_queries.append(sql)

    event.listen(db, "do_orm_execute", capture_lock)
    try:
        def reject_pin(*_):
            assert len(locked_queries) == 1
            return False

        with patch("app.api.v1.endpoints.auth.verify_pin", side_effect=reject_pin):
            response = client.post(
                "/api/v1/auth/login/pin", json={"user_id": child.id, "pin": "0000"}
            )
        assert response.status_code == 401
        assert len(locked_queries) == 1
        assert "usuarios.id" in locked_queries[0]
    finally:
        event.remove(db, "do_orm_execute", capture_lock)
