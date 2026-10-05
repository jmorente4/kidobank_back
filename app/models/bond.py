import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Float, Enum, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class BondStatus(str, enum.Enum):
    ACTIVO = "ACTIVO"
    COMPLETADO = "COMPLETADO"  # Llegó a término y cobró intereses
    RESCATADO = "RESCATADO"    # Rescatado antes de tiempo con penalización


class BondOffer(Base):
    """Oferta de renta fija publicada por un padre para que sus hijos la compren."""

    __tablename__ = "ofertas_bonos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    padre_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    tasa_interes: Mapped[float] = mapped_column(Float, nullable=False)
    plazo_dias: Mapped[int] = mapped_column(Integer, nullable=False)
    monto_minimo: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Bond(Base):
    __tablename__ = "bonos_renta_fija"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    cuenta_origen_id: Mapped[int] = mapped_column(Integer, ForeignKey("cuentas.id"), nullable=False)
    
    titulo: Mapped[str] = mapped_column(String(150), nullable=False, default="Bono del Estado Familiar")
    monto_invertido: Mapped[float] = mapped_column(Float, nullable=False)
    tasa_interes: Mapped[float] = mapped_column(Float, nullable=False)  # Ej: 0.05 para 5% de rendimiento total o periódico
    plazo_dias: Mapped[int] = mapped_column(Integer, nullable=False)      # Ej: 14 o 30 días
    
    fecha_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    fecha_vencimiento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False
    )
    
    estado: Mapped[BondStatus] = mapped_column(
        Enum(BondStatus), 
        nullable=False, 
        default=BondStatus.ACTIVO
    )
    penalizacion_aplicada: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Relaciones
    usuario: Mapped["User"] = relationship("User", backref="bonos")
    cuenta_origen: Mapped["Account"] = relationship("Account", backref="bonos")