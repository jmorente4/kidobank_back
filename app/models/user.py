import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Enum, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class UserRole(str, enum.Enum):
    PADRE = "PADRE"
    NINO = "NINO"


class User(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.NINO)
    padre_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qr_uuid: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_por_pin: Mapped[bool] = mapped_column(default=False, nullable=False)
    bloqueado_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tarjetas_qr = relationship("QrCard", back_populates="usuario", cascade="all, delete-orphan")
    avatar: Mapped[Optional["UserAvatar"]] = relationship(
        "UserAvatar", back_populates="usuario", cascade="all, delete-orphan"
    )

    items_vendidos: Mapped[List["MarketItem"]] = relationship(
        "MarketItem",
        foreign_keys="MarketItem.vendedor_id",
        back_populates="vendedor",
        cascade="all, delete-orphan",
    )
    items_comprados: Mapped[List["MarketItem"]] = relationship(
        "MarketItem",
        foreign_keys="MarketItem.comprador_id",
        back_populates="comprador",
    )
    inversiones: Mapped[List["UserInvestment"]] = relationship(
        "UserInvestment",
        back_populates="usuario",
        cascade="all, delete-orphan",
    )
    
    cuentas: Mapped[List["Account"]] = relationship(
        "Account", 
        back_populates="usuario", 
        cascade="all, delete-orphan"
    )
    padre: Mapped[Optional["User"]] = relationship(
        "User", remote_side="User.id", back_populates="hijos"
    )
    hijos: Mapped[List["User"]] = relationship("User", back_populates="padre")