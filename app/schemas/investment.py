from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.investment import InvestmentStatus, InvestmentType


class InvestmentProductCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100, description="Nombre del activo")
    codigo: str = Field(..., min_length=2, max_length=20, description="Código interno del activo")
    tipo: InvestmentType = Field(..., description="Tipo de activo: BONO o INDICE")
    descripcion: Optional[str] = Field(None, max_length=500, description="Descripción del activo")
    precio_actual_kidos: float = Field(..., gt=0, description="Precio actual del activo")
    tasa_rentabilidad: float = Field(default=0.05, ge=0, le=0.2, description="Tasa de rentabilidad anual esperada (sesgo alcista)")
    duracion_dias: Optional[int] = Field(None, ge=1, description="Plazo de inversión en días")
    volatilidad: float = Field(default=0.03, ge=0, le=1, description="Volatilidad semanal del activo (0.03 = 3%)")


class InvestmentProductResponse(BaseModel):
    id: int
    nombre: str
    codigo: str
    tipo: InvestmentType
    descripcion: Optional[str] = None
    precio_actual_kidos: float
    tasa_rentabilidad: float
    duracion_dias: Optional[int] = None
    variacion_pct: float
    volatilidad: float
    activo: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SimulationRequest(BaseModel):
    pasos: int = Field(default=1, ge=1, le=52, description="Número de semanas a simular")
    seed: Optional[int] = Field(None, description="Semilla para resultados reproducibles")


class SellInvestmentRequest(BaseModel):
    cuenta_id: int = Field(..., description="Cuenta corriente que recibe el dinero de la venta")


class SellInvestmentResponse(BaseModel):
    inversion_id: int
    monto_invertido_kidos: float
    monto_recibido_kidos: float
    resultado_kidos: float
    estado: InvestmentStatus


class InvestmentPurchaseRequest(BaseModel):
    cuenta_id: int = Field(..., description="Cuenta corriente desde la que se invierte")
    monto_invertido_kidos: float = Field(..., gt=0, description="Cantidad a invertir")


class UserInvestmentResponse(BaseModel):
    id: int
    usuario_id: int
    producto_id: int
    monto_invertido_kidos: float
    participaciones: Optional[float] = None
    fecha_inicio: datetime
    fecha_vencimiento: Optional[datetime] = None
    estado: InvestmentStatus

    model_config = ConfigDict(from_attributes=True)


class MarketNewsCreate(BaseModel):
    titulo: str = Field(..., min_length=2, max_length=150)
    descripcion: str = Field(..., min_length=2, max_length=500)
    impacto_pct: float = Field(..., description="Impacto porcentual del evento sobre el valor del activo")
    producto_id: Optional[int] = None


class MarketNewsResponse(BaseModel):
    id: int
    titulo: str
    descripcion: str
    impacto_pct: float
    producto_id: Optional[int] = None
    precio_anterior: Optional[float] = None
    precio_resultante: Optional[float] = None
    activo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvestmentPriceHistoryResponse(BaseModel):
    id: int
    producto_id: int
    precio_kidos: float
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)
