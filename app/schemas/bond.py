from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.bond import BondStatus


class BondOfferCreate(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=150, description="Nombre del bono")
    tasa_interes: float = Field(..., ge=0, description="Interés garantizado al vencimiento (ej. 0.05 para 5%)")
    plazo_dias: int = Field(..., gt=0, description="Plazo del bono en días")
    monto_minimo: float = Field(default=0.0, ge=0, description="Importe mínimo que el hijo puede invertir")


class BondOfferResponse(BaseModel):
    id: int
    padre_id: int
    titulo: str
    tasa_interes: float
    plazo_dias: int
    monto_minimo: float
    activa: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BondCreate(BaseModel):
    oferta_id: int = Field(..., description="ID de la oferta de bono que se compra")
    cuenta_origen_id: int = Field(..., description="ID de la cuenta del hijo de donde saldrán los fondos")
    monto_invertido: float = Field(..., gt=0, description="Cantidad de Kidos a invertir (debe ser mayor a 0)")


class BondResponse(BaseModel):
    id: int
    usuario_id: int
    cuenta_origen_id: int
    titulo: str
    monto_invertido: float
    tasa_interes: float
    plazo_dias: int
    fecha_inicio: datetime
    fecha_vencimiento: datetime
    estado: BondStatus
    penalizacion_aplicada: float

    class Config:
        from_attributes = True