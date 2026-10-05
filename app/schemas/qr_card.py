from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class QrCardCreate(BaseModel):
    qr_uuid: Optional[str] = Field(
        None, min_length=8, max_length=36, description="Código de la tarjeta física; se genera uno si se omite"
    )


class QrCardUpdate(BaseModel):
    activa: bool


class QrCardResponse(BaseModel):
    id: int
    usuario_id: int
    qr_uuid: str
    activa: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
