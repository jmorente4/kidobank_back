import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class UserRole(str, enum.Enum):
    PADRE = "PADRE"
    NINO = "NINO"


class User(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=True)  # Solo para PADRE
    password_hash = Column(String(255), nullable=True)                   # Solo para PADRE
    pin_hash = Column(String(255), nullable=False)                       # Hash bcrypt del PIN de 4 dígitos
    rol = Column(Enum(UserRole), default=UserRole.NINO, nullable=False)
    avatar_url = Column(String(255), nullable=True)
    intentos_fallidos = Column(Integer, default=0, nullable=False)
    bloqueado_hasta = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relaciones
    cuentas = relationship("Account", back_populates="usuario", cascade="all, delete-orphan")
    tarjetas_qr = relationship("QrCard", back_populates="usuario", cascade="all, delete-orphan")
    items_vendidos = relationship("MarketItem", foreign_keys="MarketItem.vendedor_id", back_populates="vendedor")
    items_comprados = relationship("MarketItem", foreign_keys="MarketItem.comprador_id", back_populates="comprador")
    inversiones = relationship("UserInvestment", back_populates="usuario", cascade="all, delete-orphan")