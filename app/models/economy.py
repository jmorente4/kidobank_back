import enum
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String, DateTime, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class InflationPolicyStatus(str, enum.Enum):
    ACTIVA = "ACTIVA"
    PAUSADA = "PAUSADA"


class InflationPolicy(Base):
    __tablename__ = "politicas_inflacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, default="Inflación familiar")
    tasa_semanal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ultima_aplicacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    estado: Mapped[InflationPolicyStatus] = mapped_column(Enum(InflationPolicyStatus), nullable=False, default=InflationPolicyStatus.ACTIVA)
