import enum
from sqlalchemy import Column, Integer, String, Text, Numeric, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class MarketStatus(str, enum.Enum):
    DISPONIBLE = "disponible"
    ESCROW = "escrow"
    VENDIDO = "vendido"


class MarketItem(Base):
    __tablename__ = "mercadillo_items"

    id = Column(Integer, primary_key=True, index=True)
    vendedor_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    comprador_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    titulo = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio_kidos = Column(Numeric(12, 2), nullable=False)
    estado = Column(Enum(MarketStatus), default=MarketStatus.DISPONIBLE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    vendedor = relationship("User", foreign_keys=[vendedor_id], back_populates="items_vendidos")
    comprador = relationship("User", foreign_keys=[comprador_id], back_populates="items_comprados")