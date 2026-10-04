from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.transaction import TransactionType, TransactionStatus


class TransactionCreate(BaseModel):
    cuenta_origen_id: Optional[int] = Field(None, description="ID de la cuenta origen (opcional en depósitos)")
    cuenta_destino_id: Optional[int] = Field(None, description="ID de la cuenta destino (opcional en retiros)")
    monto: float = Field(..., gt=0, description="Monto en Kidos de la transacción")
    concepto: str = Field(..., max_length=255, description="Motivo o concepto del movimiento")
    tipo: TransactionType = TransactionType.TRANSFERENCIA


class TransactionResponse(BaseModel):
    id: int
    cuenta_origen_id: Optional[int] = None
    cuenta_destino_id: Optional[int] = None
    monto: float
    concepto: str
    tipo: TransactionType
    estado: TransactionStatus
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)