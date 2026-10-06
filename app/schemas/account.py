from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.account import AccountType


class AccountBase(BaseModel):
    tipo: AccountType = AccountType.CORRIENTE
    tasa_interes: float = Field(default=0.0, ge=0.0, description="Tasa de interés de la cuenta (ej: 0.05 para 5%)")


class AccountCreate(AccountBase):
    usuario_id: int = Field(..., description="ID del usuario propietario de la cuenta")
    nombre: str = Field(..., min_length=1, max_length=50, description="Nombre de la cuenta, único para cada usuario")
    saldo_inicial: float = Field(default=0.0, ge=0.0, description="Saldo inicial en Kidos")

    @field_validator("nombre")
    @classmethod
    def _strip_nombre(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre de la cuenta no puede estar vacío")
        return value


class AccountUpdate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=50, description="Nuevo nombre, único para cada usuario")

    @field_validator("nombre")
    @classmethod
    def _strip_nombre(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre de la cuenta no puede estar vacío")
        return value


class AccountResponse(AccountBase):
    id: int
    usuario_id: int
    nombre: str
    saldo: float
    valor_bonos: Optional[float] = Field(None, description="Solo en cuentas de inversión: valor de los bonos activos")
    valor_inversiones: Optional[float] = Field(
        None, description="Solo en cuentas de inversión: valor de mercado de las posiciones activas"
    )
    patrimonio_total: Optional[float] = Field(
        None, description="Solo en cuentas de inversión: saldo + bonos + inversiones"
    )

    model_config = ConfigDict(from_attributes=True)


class TransferRequest(BaseModel):
    cuenta_origen_id: int = Field(..., description="ID de la cuenta desde la que se retira el saldo")
    cuenta_destino_id: int = Field(..., description="ID de la cuenta a la que se ingresa el saldo")
    monto: float = Field(..., gt=0, description="Monto en Kidos a transferir (debe ser mayor a 0)")
    concepto: Optional[str] = Field(default="Transferencia entre cuentas", max_length=255)