import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class MarketStatus(str, enum.Enum):
    DISPONIBLE = "DISPONIBLE"
    ESCROW = "ESCROW"
    VENDIDO = "VENDIDO"
    CANCELADO = "CANCELADO"


class EscrowStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    CANCELADO = "CANCELADO"
    REEMBOLSADO = "REEMBOLSADO"


class MarketItem(Base):
    __tablename__ = "mercadillo_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendedor_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    comprador_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    precio_kidos: Mapped[float] = mapped_column(Float, nullable=False)
    estado: Mapped[MarketStatus] = mapped_column(Enum(MarketStatus), default=MarketStatus.DISPONIBLE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    vendedor: Mapped["User"] = relationship("User", foreign_keys=[vendedor_id], back_populates="items_vendidos")
    comprador: Mapped[Optional["User"]] = relationship("User", foreign_keys=[comprador_id], back_populates="items_comprados")
    escrows: Mapped[List["EscrowTransaction"]] = relationship("EscrowTransaction", back_populates="item", cascade="all, delete-orphan")


class EscrowTransaction(Base):
    __tablename__ = "mercadillo_escrows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("mercadillo_items.id", ondelete="CASCADE"), nullable=False, index=True)
    comprador_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    vendedor_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    monto: Mapped[float] = mapped_column(Float, nullable=False)
    estado: Mapped[EscrowStatus] = mapped_column(Enum(EscrowStatus), default=EscrowStatus.PENDIENTE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    item: Mapped["MarketItem"] = relationship("MarketItem", back_populates="escrows")
    comprador: Mapped["User"] = relationship("User", foreign_keys=[comprador_id], backref="escrows_comprados")
    vendedor: Mapped["User"] = relationship("User", foreign_keys=[vendedor_id], backref="escrows_vendidos")