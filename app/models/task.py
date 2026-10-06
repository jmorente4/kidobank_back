import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class TaskStatus(str, enum.Enum):
    ASIGNADA = "ASIGNADA"
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"
    COMPLETADA = "COMPLETADA"


class Task(Base):
    __tablename__ = "tareas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    creado_por_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    recompensa_kidos: Mapped[float] = mapped_column(Float, nullable=False)
    estado: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), nullable=False, default=TaskStatus.ASIGNADA
    )
    cuenta_abono_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cuentas.id", ondelete="SET NULL"), nullable=True
    )
    completada_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    aprobada_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    aprobada_por_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
