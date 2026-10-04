# seed_db.py
import logging
import sys
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.account import Account, AccountType
from app.models.user import User, UserRole

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def seed_data() -> None:
    logger.info("🌱 Iniciando el sembrado inicial de la base de datos...")

    # Asegurar que todas las tablas existen antes de poblar
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Verificar si ya existe al menos un usuario Administrador/Padre
        existing_admin = db.scalars(select(User).where(User.rol == UserRole.PADRE)).first()
        if existing_admin:
            logger.info("⚠️ Ya existe un usuario Padre/Admin en la base de datos. Se omite el seeding.")
            return

        # ----------------------------------------------------
        # Crear Usuario Padre / Administrador Principal
        # ----------------------------------------------------
        logger.info("👤 Creando usuario Padre/Administrador principal...")
        padre = User(
            nombre="Papá Carlos",
            email="padre@kidobank.com",
            pin_hash=get_password_hash("padre123"),
            rol=UserRole.PADRE,
            qr_uuid="QR-PADRE-001",
        )
        db.add(padre)
        db.flush()

        # Crear Cuenta Principal para el Padre (Fondo familiar)
        cuenta_padre = Account(
            usuario_id=padre.id,
            tipo=AccountType.CORRIENTE,
            saldo=1000.0,
            tasa_interes=0.0,
        )
        db.add(cuenta_padre)

        db.commit()

        logger.info("✅ Base de datos inicializada correctamente.")
        logger.info("=" * 60)
        logger.info("CREDANCIALES DE ADMINISTRADOR INICIALES:")
        logger.info(" 👨 PADRE/ADMIN: Email: padre@kidobank.com | Password: padre123")
        logger.info("=" * 60)

    except Exception as e:
        db.rollback()
        logger.error("❌ Error durante el sembrado de la base de datos: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()