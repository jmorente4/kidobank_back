import enum
from sqlalchemy import Column, Integer, Numeric, Enum, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class AccountType(str, enum.Enum):
    CORRIENTE = "corriente"
    AHORRO = "ahorro"
    INVERSION = "inversion"


class Account(Base):
    __tablename__ = "cuentas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(Enum(AccountType), nullable=False)
    saldo_kidos = Column(Numeric(12, 2), default=0.00, nullable=False)
    tasa_interes_anual = Column(Numeric(5, 2), default=0.00, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('usuario_id', 'tipo', name='_usuario_tipo_cuenta_uc'),
    )

    # Relaciones
    usuario = relationship("User", back_populates="cuentas")
    transacciones_origen = relationship("Transaction", foreign_keys="Transaction.cuenta_origen_id", back_populates="cuenta_origen")
    transacciones_destino = relationship("Transaction", foreign_keys="Transaction.cuenta_destino_id", back_populates="cuenta_destino")