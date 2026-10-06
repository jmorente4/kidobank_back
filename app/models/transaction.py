import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Float, Enum, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class TransactionType(str, enum.Enum):
    DEPOSITO = "DEPOSITO"          # Ingreso directo
    RETIRO = "RETIRO"              # Extracción de fondos
    TRANSFERENCIA = "TRANSFERENCIA"# Entre cuentas o entre niños
    PAGA = "PAGA"                  # Paga periódica concedida por el padre
    INTERES = "INTERES"            # Rendimiento generado por la cuenta de Ahorro/Inversión
    INVERSION = "INVERSION"        # Compra o venta de un activo de inversión
    RECOMPENSA = "RECOMPENSA"      # Recompensa de una tarea aprobada


class TransactionStatus(str, enum.Enum):
    COMPLETADA = "COMPLETADA"
    PENDIENTE = "PENDIENTE"
    CANCELADA = "CANCELADA"


class Transaction(Base):
    __tablename__ = "transacciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cuenta_origen_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cuentas.id"), nullable=True, index=True
    )
    cuenta_destino_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cuentas.id"), nullable=True, index=True
    )
    monto: Mapped[float] = mapped_column(Float, nullable=False)
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False, default=TransactionType.TRANSFERENCIA
    )
    estado: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), nullable=False, default=TransactionStatus.COMPLETADA
    )
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # Relaciones
    cuenta_origen: Mapped[Optional["Account"]] = relationship(
        "Account", foreign_keys=[cuenta_origen_id], back_populates="transacciones_origen"
    )
    cuenta_destino: Mapped[Optional["Account"]] = relationship(
        "Account", foreign_keys=[cuenta_destino_id], back_populates="transacciones_destino"
    )