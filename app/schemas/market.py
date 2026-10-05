from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.market import EscrowStatus, MarketStatus


class MarketItemCreate(BaseModel):
    titulo: str = Field(..., min_length=2, max_length=150, description="Título del artículo o servicio")
    descripcion: Optional[str] = Field(None, max_length=1000, description="Descripción del producto o servicio")
    precio_kidos: float = Field(..., gt=0, description="Precio en Kidos")


class MarketItemUpdate(BaseModel):
    titulo: Optional[str] = Field(None, min_length=2, max_length=150)
    descripcion: Optional[str] = Field(None, max_length=1000)
    precio_kidos: Optional[float] = Field(None, gt=0)


class MarketItemResponse(BaseModel):
    id: int
    vendedor_id: int
    comprador_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    precio_kidos: float
    estado: MarketStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseItemRequest(BaseModel):
    cuenta_id: int = Field(..., description="Cuenta corriente del comprador desde la que se bloquean los fondos")


class EscrowResponse(BaseModel):
    id: int
    item_id: int
    comprador_id: int
    vendedor_id: int
    monto: float
    estado: EscrowStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
