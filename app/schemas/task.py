from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskStatus


class TaskCreate(BaseModel):
    usuario_id: int = Field(..., description="Hijo al que se asigna la tarea")
    titulo: str = Field(..., min_length=2, max_length=150)
    descripcion: Optional[str] = Field(None, max_length=500)
    recompensa_kidos: float = Field(..., gt=0)


class TaskApprove(BaseModel):
    cuenta_id: int = Field(..., description="Cuenta corriente del hijo que recibe el premio")


class TaskResponse(BaseModel):
    id: int
    usuario_id: int
    creado_por_id: int
    titulo: str
    descripcion: Optional[str] = None
    recompensa_kidos: float
    estado: TaskStatus
    cuenta_abono_id: Optional[int] = None
    completada_at: Optional[datetime] = None
    aprobada_at: Optional[datetime] = None
    aprobada_por_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
