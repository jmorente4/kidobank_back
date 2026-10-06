from sqlalchemy import create_engine

from app.core.config import Settings


def test_generated_database_url_uses_installed_psycopg2_driver():
    settings = Settings(
        _env_file=None,
        POSTGRES_SERVER="db",
        POSTGRES_PORT=5432,
        POSTGRES_USER="testuser",
        POSTGRES_PASSWORD="testpassword",
        POSTGRES_DB="testdb",
        SECRET_KEY="test-only-not-for-deployment",
        DATABASE_URL="",
    )
    assert settings.DATABASE_URL == (
        "postgresql+psycopg2://testuser:testpassword@db:5432/testdb"
    )
    engine = create_engine(settings.DATABASE_URL)
    try:
        assert engine.dialect.driver == "psycopg2"
    finally:
        engine.dispose()
