import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.security import get_password_hash, get_pin_hash
from app.db.base import Base
from app.main import app
from app.models.account import Account
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