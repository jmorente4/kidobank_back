import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class GoalStatus(str, enum.Enum):
    ACTIVA = "ACTIVA"
    COMPLETADA = "COMPLETADA"
    PAUSADA = "PAUSADA"


class Goal(Base):
    __tablename__ = "metas_ahorro"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    cuenta_id: Mapped[int] = mapped_column(Integer, ForeignKey("cuentas.id", ondelete="CASCADE"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    monto_objetivo: Mapped[float] = mapped_column(Float, nullable=False)
    monto_actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    icono: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    estado: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), nullable=False, default=GoalStatus.ACTIVA)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    usuario: Mapped["User"] = relationship("User", backref="metas")
    cuenta: Mapped["Account"] = relationship("Account", backref="metas")
