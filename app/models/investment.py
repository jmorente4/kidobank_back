import enum
from sqlalchemy import Column, Integer, String, Numeric, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class InvestmentType(str, enum.Enum):
    BONO = "bono"
    INDICE = "indice"


class InvestmentStatus(str, enum.Enum):
    ACTIVA = "activa"
    LIQUIDADA = "liquidada"
    CANCELADA = "cancelada"


class InvestmentProduct(Base):
    __tablename__ = "productos_inversion"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    codigo = Column(String(20), unique=True, index=True, nullable=False)
    tipo = Column(Enum(InvestmentType), nullable=False)
    precio_actual_kidos = Column(Numeric(12, 2), nullable=False)
    tasa_rentabilidad = Column(Numeric(5, 2), default=0.00, nullable=False)
    duracion_dias = Column(Integer, nullable=True)

    inversiones_usuarios = relationship("UserInvestment", back_populates="producto")


class UserInvestment(Base):
    __tablename__ = "inversiones_usuarios"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos_inversion.id", ondelete="CASCADE"), nullable=False)
    monto_invertido_kidos = Column(Numeric(12, 2), nullable=False)
    participaciones = Column(Numeric(12, 4), nullable=True)
    fecha_inicio = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_vencimiento = Column(DateTime(timezone=True), nullable=True)
    estado = Column(Enum(InvestmentStatus), default=InvestmentStatus.ACTIVA, nullable=False)

    usuario = relationship("User", back_populates="inversiones")
    producto = relationship("InvestmentProduct", back_populates="inversiones_usuarios")