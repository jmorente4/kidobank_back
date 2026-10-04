import enum
from sqlalchemy import Column, Integer, String, Numeric, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class TransactionType(str, enum.Enum):
    PAGA = "paga"
    TRANSFERENCIA = "transferencia"
    COMPRA_MERCADILLO = "compra_mercadillo"
    INTERES_AHORRO = "interes_ahorro"
    INVERSION_BONO = "inversion_bono"
    INVERSION_BOLSA = "inversion_bolsa"


class Transaction(Base):
    __tablename__ = "transacciones"

    id = Column(Integer, primary_key=True, index=True)
    cuenta_origen_id = Column(Integer, ForeignKey("cuentas.id", ondelete="SET NULL"), nullable=True)
    cuenta_destino_id = Column(Integer, ForeignKey("cuentas.id", ondelete="SET NULL"), nullable=True)
    monto_kidos = Column(Numeric(12, 2), nullable=False)
    tipo = Column(Enum(TransactionType), nullable=False)
    concepto = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relaciones
    cuenta_origen = relationship("Account", foreign_keys=[cuenta_origen_id], back_populates="transacciones_origen")
    cuenta_destino = relationship("Account", foreign_keys=[cuenta_destino_id], back_populates="transacciones_destino")