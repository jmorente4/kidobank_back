from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.account import AccountType


class AccountBase(BaseModel):
    tipo: AccountType = AccountType.CORRIENTE
    tasa_interes: float = Field(default=0.0, ge=0.0, description="Tasa de interés de la cuenta (ej: 0.05 para 5%)")


class AccountCreate(AccountBase):
    usuario_id: int = Field(..., description="ID del usuario propietario de la cuenta")
    saldo_inicial: float = Field(default=0.0, ge=0.0, description="Saldo inicial en Kidos")


class AccountResponse(AccountBase):
    id: int
    usuario_id: int
    saldo: float
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class TransferRequest(BaseModel):
    cuenta_origen_id: int = Field(..., description="ID de la cuenta desde la que se retira el saldo")
    cuenta_destino_id: int = Field(..., description="ID de la cuenta a la que se ingresa el saldo")
    monto: float = Field(..., gt=0, description="Monto en Kidos a transferir (debe ser mayor a 0)")
    concepto: Optional[str] = Field(default="Transferencia entre cuentas", max_length=255)