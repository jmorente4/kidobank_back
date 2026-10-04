import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class UserRole(str, enum.Enum):
    PADRE = "PADRE"
    NINO = "NINO"


class User(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.NINO)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qr_uuid: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    cuentas: Mapped[List["Account"]] = relationship(
        "Account", 
        back_populates="usuario", 
        cascade="all, delete-orphan"
    )