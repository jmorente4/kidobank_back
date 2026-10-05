import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base_class import Base
from app.api.deps import get_db
from app.main import app
from app.models.user import User, UserRole
from app.core.security import get_password_hash

# Base de datos SQLite en memoria para tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    """Crea una nueva base de datos para cada test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Cliente de pruebas de FastAPI con inyección de la base de datos de test."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def padre_user(db):
    """Crea un usuario PADRE por defecto en la BD de test para los flujos autenticados."""
    padre = User(
        nombre="Padre Test",
        email="padre.test@kidobank.com",
        pin_hash=get_password_hash("padre123"),  # O password según tu lógica de login
        rol=UserRole.PADRE,
    )
    db.add(padre)
    db.commit()
    db.refresh(padre)
    return padre