from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.bond import BondStatus


class BondCreate(BaseModel):
    cuenta_origen_id: int = Field(..., description="ID de la cuenta de donde saldrán los fondos para comprar el bono")
    titulo: Optional[str] = Field("Bono del Estado Familiar", description="Nombre o descripción del bono")
    monto_invertido: float = Field(..., gt=0, description="Cantidad de Kidos a invertir (debe ser mayor a 0)")
    plazo_dias: int = Field(..., gt=0, description="Plazo de duración del bono en días")
    tasa_interes: float = Field(..., ge=0, description="Tasa de interés total o periódica garantizada (ej. 0.05 para 5%)")


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