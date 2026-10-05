from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from app.models.account import AccountType
from app.models.economy import InflationPolicyStatus


class InflationPolicyCreate(BaseModel):
    tasa_semanal: float = Field(..., ge=0, lt=1, description="Tasa de inflación semanal expresada como decimal: 0.02 = 2%")
    nombre: str = Field(default="Inflación familiar", min_length=2, max_length=100)


class InflationPolicyResponse(BaseModel):
    id: int
    nombre: str
    tasa_semanal: float
    activa: bool
    estado: InflationPolicyStatus
    fecha_actualizacion: datetime
    ultima_aplicacion: datetime

    model_config = ConfigDict(from_attributes=True)


class SavingsRateUpdate(BaseModel):
    tasa_semanal: float = Field(..., ge=0, lt=1, description="Interés fijo semanal; 0.02 representa el 2% semanal")


class SavingsRateResponse(BaseModel):
    cuenta_id: int
    tasa_semanal: float


class AccountSummary(BaseModel):
    cuenta_id: int
    tipo: AccountType
    saldo: float
    tasa_nominal_periodo: float = Field(..., description="tasa_interes de la cuenta por periodo semanal")
    tasa_nominal_semanal: float = Field(..., description="Interés nominal semanal de la cuenta")
    tasa_real_semanal: float = Field(..., description="(1 + nominal semanal) / (1 + inflación semanal) - 1")


class WealthSummary(BaseModel):
    usuario_id: int
    cuentas: List[AccountSummary]
    saldo_corriente: float
    saldo_ahorro: float
    saldo_cuentas_inversion: float
    valor_inversiones_mercado: float
    valor_bonos_activos: float
    valor_metas_ahorro: float
    fondos_en_escrow: float
    patrimonio_total: float
    inflacion_semanal: float
