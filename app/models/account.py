import enum
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, Float, Enum, DateTime, ForeignKey, Index, func, literal_column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class AccountType(str, enum.Enum):
    CORRIENTE = "CORRIENTE"
    AHORRO = "AHORRO"
    INVERSION = "INVERSION"


class Account(Base):
    __tablename__ = "cuentas"
    __table_args__ = (Index("uq_cuentas_usuario_nombre", "usuario_id", func.lower(literal_column("nombre")), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False, default="Cuenta corriente")
    tipo: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False, default=AccountType.CORRIENTE)
    saldo: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tasa_interes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # Ej: 0.05 para 5%
    ultimo_abono_interes: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    usuario: Mapped["User"] = relationship("User", back_populates="cuentas")
    
    transacciones_origen: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        foreign_keys="Transaction.cuenta_origen_id",
        back_populates="cuenta_origen",
        cascade="all, delete-orphan"
    )
    transacciones_destino: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        foreign_keys="Transaction.cuenta_destino_id",
        back_populates="cuenta_destino",
        cascade="all, delete-orphan"
    )