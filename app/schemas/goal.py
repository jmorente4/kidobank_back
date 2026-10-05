from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.goal import GoalStatus


class GoalCreate(BaseModel):
    cuenta_id: int = Field(..., description="ID de la cuenta del niño a la que se vincula la meta")
    titulo: str = Field(..., min_length=2, max_length=150, description="Título de la meta")
    descripcion: Optional[str] = Field(None, max_length=500, description="Descripción opcional de la meta")
    monto_objetivo: float = Field(..., gt=0, description="Cantidad total que debe ahorrar")
    icono: Optional[str] = Field(None, max_length=50, description="Icono o emoji representativo")


class GoalDeposit(BaseModel):
    monto: float = Field(..., gt=0, description="Cantidad a aportar a la meta")


class GoalResponse(BaseModel):
    id: int
    usuario_id: int
    cuenta_id: int
    titulo: str
    descripcion: Optional[str] = None
    monto_objetivo: float
    monto_actual: float
    icono: Optional[str] = None
    estado: GoalStatus
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)
