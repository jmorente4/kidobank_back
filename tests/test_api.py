import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.security import get_password_hash, get_pin_hash
from app.db.base import Base
from app.db.compatibility import ensure_family_columns
from app.main import app
from app.models.account import Account
from app.models.goal import Goal
from app.models.user import User, UserRole

# ----------------------------------------------------------------------
# Configuración de Base de Datos SQLite en memoria para tests
# ----------------------------------------------------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Reemplazar la dependencia de la BD principal por la de pruebas
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Crea las tablas antes de cada test y las elimina al finalizar."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Cliente HTTP de pruebas para realizar peticiones a la API."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def padre_user():
    """Inserta un usuario Padre inicial en la BD de pruebas."""
    db = TestingSessionLocal()
    padre = User(
        nombre="Papá Test",
        email="padre.test@kidobank.com",
        pin_hash=get_password_hash("padre123"),  # O hashed_password segun tu modelo User
        rol=UserRole.PADRE,
    )
    db.add(padre)
    db.commit()
    db.refresh(padre)
    db.close()
    return padre


# ----------------------------------------------------------------------
# Pruebas de Autenticación
# ----------------------------------------------------------------------
def test_login_padre_exitoso(client, padre_user):
    """Verifica que un Padre pueda iniciar sesión con correo y contraseña válidos."""
    response = client.post(
        "/api/v1/auth/login/parent",
        json={
            "email": "padre.test@kidobank.com",
            "password": "padre123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "padre.test@kidobank.com"


def test_login_padre_credenciales_invalidas(client, padre_user):
    """Verifica el rechazo de credenciales incorrectas."""
    response = client.post(
        "/api/v1/auth/login/parent",
        json={
            "email": "padre.test@kidobank.com",
            "password": "password_incorrecta",
        },
    )
    assert response.status_code == 401


# ----------------------------------------------------------------------
# Pruebas del Flujo Completo: Alta de Niño y Login por PIN
# ----------------------------------------------------------------------
def test_flujo_creacion_y_login_nino(client, padre_user):
    """
    Verifica el flujo completo:
    1. El Padre obtiene su token de sesión.
    2. El Padre registra un nuevo usuario Niño.
    3. Se comprueba que la API creó automáticamente la cuenta bancaria del Niño.
    4. El Niño inicia sesión con su PIN.
    """
    # 1. Obtener Token del Padre
    login_res = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Registrar al Niño usando las credenciales del Padre
    nuevo_nino_data = {
        "nombre": "Leo Test",
        "email": "leo.test@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "5678",
        "tarjeta_qr": "QR-LEO-TEST-99",
    }
    create_res = client.post("/api/v1/users/", json=nuevo_nino_data, headers=headers)
    print("ERROR RESPONSE:", create_res.json())
    assert create_res.status_code == 201
    nino_created = create_res.json()
    assert nino_created["nombre"] == "Leo Test"
    assert nino_created["rol"] == "NINO"

    nino_id = nino_created["id"]

    # 3. Verificar que se le asignó automáticamente su cuenta corriente en la BD
    db = TestingSessionLocal()
    cuenta_nino = db.query(Account).filter(Account.usuario_id == nino_id).first()
    assert cuenta_nino is not None
    assert cuenta_nino.saldo == 0.0
    db.close()

    # 4. El Niño inicia sesión mediante PIN
    pin_login_res = client.post(
        "/api/v1/auth/login/pin",
        json={
            "user_id": nino_id,
            "pin": "5678",
        },
    )
    assert pin_login_res.status_code == 200
    pin_data = pin_login_res.json()
    assert "access_token" in pin_data
    assert pin_data["user"]["id"] == nino_id


def test_crear_nino_sin_autorizacion(client):
    """Verifica que un usuario anónimo o no autorizado no pueda crear niños."""
    nuevo_nino_data = {
        "nombre": "Intruso",
        "email": "intruso@kidobank.com",
        "password": "password123",
        "rol": "NINO",
        "codigo_pin": "9999",
    }
    response = client.post("/api/v1/users/", json=nuevo_nino_data)
    assert response.status_code in (401, 403)


def test_registro_publico_permite_adultos_y_no_ninos(client):
    payload = {
        "nombre": "Primer padre",
        "email": "primer.padre@kidobank.com",
        "rol": "PADRE",
        "password": "segura123",
    }
    first = client.post("/api/v1/users/", json=payload)
    assert first.status_code == 201
    assert first.json()["rol"] == "PADRE"
    assert client.get("/api/v1/accounts/user/1").status_code == 401

    payload["email"] = "segundo.padre@kidobank.com"
    second = client.post("/api/v1/users/", json=payload)
    assert second.status_code == 201
    payload.update({"email": "hijo.sin.padre@kidobank.com", "rol": "NINO", "codigo_pin": "9876"})
    assert client.post("/api/v1/users/", json=payload).status_code == 403


def test_padre_solo_consulta_sus_hijos_y_sus_datos(client, padre_user):
    login = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "padre123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    child_response = client.post(
        "/api/v1/users/children",
        headers=headers,
        json={
            "nombre": "Hijo vinculado",
            "email": "hijo.vinculado@kidobank.com",
            "rol": "NINO",
            "codigo_pin": "2468",
        },
    )
    assert child_response.status_code == 201
    child_id = child_response.json()["id"]
    assert child_response.json()["padre_id"] == padre_user.id
    assert [child["id"] for child in client.get("/api/v1/users/children", headers=headers).json()] == [child_id]
    assert client.get(f"/api/v1/accounts/user/{child_id}", headers=headers).status_code == 200
    child_account_id = client.get(
        f"/api/v1/accounts/user/{child_id}", headers=headers
    ).json()[0]["id"]
    pay_response = client.post(
        "/api/v1/transactions/paga",
        headers=headers,
        json={"cuenta_destino_id": child_account_id, "monto": 5.0},
    )
    assert pay_response.status_code == 201
    child_transactions = client.get(
        f"/api/v1/transactions/user/{child_id}", headers=headers
    ).json()
    assert [tx["tipo"] for tx in child_transactions] == ["PAGA"]

    db = TestingSessionLocal()
    other_parent = User(
        nombre="Otro padre",
        email="otro.padre@kidobank.com",
        pin_hash=get_password_hash("padre123"),
        rol=UserRole.PADRE,
    )
    db.add(other_parent)
    db.flush()
    other_child = User(
        nombre="Hijo ajeno",
        email="hijo.ajeno@kidobank.com",
        pin_hash=get_password_hash("1234"),
        rol=UserRole.NINO,
        padre_id=other_parent.id,
    )
    db.add(other_child)
    db.flush()
    other_account = Account(usuario_id=other_child.id, saldo=5.0)
    db.add(other_account)
    db.flush()
    other_goal = Goal(
        usuario_id=other_child.id,
        cuenta_id=other_account.id,
        titulo="Meta ajena",
        monto_objetivo=10.0,
    )
    db.add(other_goal)
    db.commit()
    other_child_id = other_child.id
    other_account_id = other_account.id
    other_goal_id = other_goal.id
    db.close()

    assert client.get(f"/api/v1/users/{other_child_id}", headers=headers).status_code == 403
    assert client.get(f"/api/v1/accounts/user/{other_child_id}", headers=headers).status_code == 403
    assert client.get(f"/api/v1/accounts/{other_account_id}", headers=headers).status_code == 403
    assert client.get(f"/api/v1/transactions/user/{other_child_id}", headers=headers).status_code == 403
    assert client.get("/api/v1/goals/", headers=headers).json() == []
    assert client.post(
        f"/api/v1/goals/{other_goal_id}/deposit",
        headers=headers,
        json={"monto": 1.0},
    ).status_code == 403
    assert client.get("/api/v1/accounts/user/99999", headers=headers).status_code == 404


def test_login_con_email_inexistente_devuelve_401(client):
    response = client.post(
        "/api/v1/auth/login/parent",
        json={"email": "no.existe@kidobank.com", "password": "incorrecta"},
    )
    assert response.status_code == 401


def test_login_invalido_no_falla_al_bloquear_temporalmente(client, padre_user):
    endpoint = "/api/v1/auth/login/parent"
    payload = {"email": "padre.test@kidobank.com", "password": "incorrecta"}
    for _ in range(3):
        assert client.post(endpoint, json=payload).status_code == 401
    assert client.post(endpoint, json=payload).status_code == 403


def test_recuperacion_de_contrasena_con_token_de_un_solo_uso(client, padre_user, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    import app.api.v1.endpoints.auth as auth_endpoint

    monkeypatch.setattr(auth_endpoint.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(auth_endpoint.settings, "SMTP_FROM_EMAIL", "no-reply@kidobank.com")
    reset_urls = []
    monkeypatch.setattr(
        auth_endpoint,
        "send_password_reset_email",
        lambda recipient, reset_url: reset_urls.append(reset_url),
    )

    response = client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "padre.test@kidobank.com"},
    )
    assert response.status_code == 202
    assert "token" not in response.json()
    assert len(reset_urls) == 1
    token = parse_qs(urlsplit(reset_urls[0]).query)["token"][0]

    reset_response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "nueva123"},
    )
    assert reset_response.status_code == 204
    assert client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "otra123"},
    ).status_code == 400
    assert client.post(
        "/api/v1/auth/login/parent",
        json={"email": "padre.test@kidobank.com", "password": "nueva123"},
    ).status_code == 200


def test_tarjeta_qr_segura_para_la_familia(client, padre_user):
    def auth(email, password):
        res = client.post("/api/v1/auth/login/parent", json={"email": email, "password": password})
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    headers = auth("padre.test@kidobank.com", "padre123")
    child = client.post(
        "/api/v1/users/",
        json={
            "nombre": "Leo", "email": "leo.card@kidobank.com", "password": "password123",
            "rol": "NINO", "codigo_pin": "5678", "tarjeta_qr": "QR-LEO-CARD-01",
        },
        headers=headers,
    ).json()

    cards = client.get(f"/api/v1/users/{child['id']}/cards", headers=headers)
    assert cards.status_code == 200
    assert [c["qr_uuid"] for c in cards.json()] == ["QR-LEO-CARD-01"]
    assert "pin" not in cards.text.lower() and "hash" not in cards.text.lower()

    assert client.get(f"/api/v1/users/{child['id']}/cards").status_code == 401

    other = client.post(
        "/api/v1/users/",
        json={"nombre": "Otro", "email": "otro.padre@kidobank.com", "password": "password123", "rol": "PADRE"},
    )
    assert other.status_code == 201
    other_headers = auth("otro.padre@kidobank.com", "password123")
    assert client.get(f"/api/v1/users/{child['id']}/cards", headers=other_headers).status_code == 403
    assert client.post(
        f"/api/v1/users/{child['id']}/cards", json={}, headers=other_headers
    ).status_code == 403

    # Un hijo puede ver su tarjeta pero no gestionarla
    pin = client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "5678"})
    child_headers = {"Authorization": f"Bearer {pin.json()['access_token']}"}
    assert client.get(f"/api/v1/users/{child['id']}/cards", headers=child_headers).status_code == 200
    assert client.post(
        f"/api/v1/users/{child['id']}/cards", json={}, headers=child_headers
    ).status_code == 403

    # Emitir una tarjeta nueva revoca la anterior
    new_card = client.post(f"/api/v1/users/{child['id']}/cards", json={}, headers=headers)
    assert new_card.status_code == 201
    assert client.post("/api/v1/auth/login/pin", json={"qr_uuid": "QR-LEO-CARD-01", "pin": "5678"}).status_code in (401, 404)
    assert client.post(
        "/api/v1/auth/login/pin", json={"qr_uuid": new_card.json()["qr_uuid"], "pin": "5678"}
    ).status_code == 200

    # Revocar y reactivar
    card_id = new_card.json()["id"]
    url = f"/api/v1/users/{child['id']}/cards/{card_id}"
    assert client.patch(url, json={"activa": False}, headers=headers).json()["activa"] is False
    assert client.post(
        "/api/v1/auth/login/pin", json={"qr_uuid": new_card.json()["qr_uuid"], "pin": "5678"}
    ).status_code in (401, 404)


def test_editar_perfil_y_cambiar_pin(client, padre_user):
    res = client.post("/api/v1/auth/login/parent", json={"email": "padre.test@kidobank.com", "password": "padre123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    child = client.post(
        "/api/v1/users/",
        json={"nombre": "Leo", "email": "leo.pin@kidobank.com", "password": "password123",
              "rol": "NINO", "codigo_pin": "5678"},
        headers=headers,
    ).json()
    url = f"/api/v1/users/{child['id']}"

    edited = client.patch(url, json={"nombre": "Leonardo", "email": "leonardo@kidobank.com"}, headers=headers)
    assert edited.status_code == 200 and edited.json()["nombre"] == "Leonardo"
    assert client.patch(url, json={"email": "padre.test@kidobank.com"}, headers=headers).status_code == 400
    assert client.patch(url, json={"nombre": "X"}).status_code == 401

    pin = client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "5678"})
    child_headers = {"Authorization": f"Bearer {pin.json()['access_token']}"}
    assert client.patch(url, json={"nombre": "Leo Jr"}, headers=child_headers).status_code == 200
    assert client.patch(f"{url}/pin", json={"pin_nuevo": "1111", "pin_actual": "0000"}, headers=child_headers).status_code == 403
    assert client.patch(f"{url}/pin", json={"pin_nuevo": "1111"}, headers=child_headers).status_code == 403
    assert client.patch(f"{url}/pin", json={"pin_nuevo": "1111", "pin_actual": "5678"}, headers=child_headers).status_code == 204
    assert client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "5678"}).status_code == 401
    assert client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "1111"}).status_code == 200

    # El padre puede restablecer el PIN sin conocer el actual
    assert client.patch(f"{url}/pin", json={"pin_nuevo": "2222"}, headers=headers).status_code == 204
    assert client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "2222"}).status_code == 200


def test_deposito_solo_padre_y_cuenta_propia(client, padre_user):
    res = client.post("/api/v1/auth/login/parent", json={"email": "padre.test@kidobank.com", "password": "padre123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    child = client.post(
        "/api/v1/users/",
        json={"nombre": "Leo", "email": "leo.dep@kidobank.com", "password": "password123",
              "rol": "NINO", "codigo_pin": "5678"},
        headers=headers,
    ).json()
    own = client.post(
        "/api/v1/accounts/", json={"usuario_id": padre_user.id, "tipo": "CORRIENTE"}, headers=headers
    ).json()
    child_acc = client.get(f"/api/v1/accounts/user/{child['id']}", headers=headers).json()[0]

    ok = client.post("/api/v1/transactions/deposito", json={"cuenta_destino_id": own["id"], "monto": 50}, headers=headers)
    assert ok.status_code == 201
    assert ok.json()["tipo"] == "DEPOSITO" and ok.json()["cuenta_origen_id"] is None
    assert ok.json()["concepto"] == "Recarga"
    after = client.get(f"/api/v1/accounts/{own['id']}", headers=headers).json()
    assert after["saldo"] == own["saldo"] + 50

    assert client.post("/api/v1/transactions/deposito", json={"cuenta_destino_id": own["id"], "monto": 0}, headers=headers).status_code == 422
    assert client.post("/api/v1/transactions/deposito", json={"cuenta_destino_id": child_acc["id"], "monto": 5}, headers=headers).status_code == 403
    assert client.post("/api/v1/transactions/deposito", json={"cuenta_destino_id": own["id"], "monto": 5}).status_code == 401

    pin = client.post("/api/v1/auth/login/pin", json={"user_id": child["id"], "pin": "5678"})
    child_headers = {"Authorization": f"Bearer {pin.json()['access_token']}"}
    assert client.post("/api/v1/transactions/deposito", json={"cuenta_destino_id": child_acc["id"], "monto": 5}, headers=child_headers).status_code == 403


def test_migracion_asocia_hijos_legacy_solo_cuando_se_anade_la_columna():
    migration_engine = create_engine("sqlite:///:memory:")
    with migration_engine.begin() as connection:
        connection.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol VARCHAR(10))"))
        connection.execute(
            text("INSERT INTO usuarios (id, rol) VALUES (1, 'PADRE'), (2, 'NINO')")
        )

    ensure_family_columns(migration_engine)
    with migration_engine.begin() as connection:
        assert connection.execute(
            text("SELECT padre_id FROM usuarios WHERE id = 2")
        ).scalar_one() == 1
        connection.execute(text("INSERT INTO usuarios (id, rol) VALUES (3, 'PADRE'), (4, 'NINO')"))

    ensure_family_columns(migration_engine)
    with migration_engine.connect() as connection:
        assert connection.execute(
            text("SELECT padre_id FROM usuarios WHERE id = 2")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT padre_id FROM usuarios WHERE id = 4")
        ).scalar_one() is None
    migration_engine.dispose()