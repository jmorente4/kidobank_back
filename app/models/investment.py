import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class InvestmentType(str, enum.Enum):
    BONO = "BONO"
    INDICE = "INDICE"


class InvestmentStatus(str, enum.Enum):
    ACTIVA = "ACTIVA"
    LIQUIDADA = "LIQUIDADA"
    CANCELADA = "CANCELADA"


class InvestmentProduct(Base):
    __tablename__ = "productos_inversion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    tipo: Mapped[InvestmentType] = mapped_column(Enum(InvestmentType), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    precio_actual_kidos: Mapped[float] = mapped_column(Float, nullable=False)
    precio_base: Mapped[float] = mapped_column(Float, nullable=False)
    tasa_rentabilidad: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duracion_dias: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    variacion_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volatilidad: Mapped[float] = mapped_column(Float, nullable=False, default=0.03)  # desviación semanal
    ultima_simulacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    semanas_bajistas_restantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    inversiones_usuarios: Mapped[list["UserInvestment"]] = relationship("UserInvestment", back_populates="producto", cascade="all, delete-orphan")


class UserInvestment(Base):
    __tablename__ = "inversiones_usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id: Mapped[int] = mapped_column(Integer, ForeignKey("productos_inversion.id", ondelete="CASCADE"), nullable=False, index=True)
    monto_invertido_kidos: Mapped[float] = mapped_column(Float, nullable=False)
    participaciones: Mapped[float] = mapped_column(Float, nullable=True)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    fecha_vencimiento: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    estado: Mapped[InvestmentStatus] = mapped_column(Enum(InvestmentStatus), default=InvestmentStatus.ACTIVA, nullable=False)

    usuario: Mapped["User"] = relationship("User", back_populates="inversiones")
    producto: Mapped[InvestmentProduct] = relationship("InvestmentProduct", back_populates="inversiones_usuarios")


class MarketNews(Base):
    __tablename__ = "noticias_mercado"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(500), nullable=False)
    impacto_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    producto_id: Mapped[Optional[int]] = mapped_column(ForeignKey("productos_inversion.id"), nullable=True, index=True)
    precio_anterior: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precio_resultante: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    activo: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class InvestmentPriceHistory(Base):
    __tablename__ = "historial_precios_inversion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    producto_id: Mapped[int] = mapped_column(
        ForeignKey("productos_inversion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    precio_kidos: Mapped[float] = mapped_column(Float, nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)