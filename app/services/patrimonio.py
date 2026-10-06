from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.bond import Bond, BondStatus
from app.models.investment import InvestmentStatus, UserInvestment
from app.schemas.account import AccountResponse


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def bond_value(bond: Bond, now: Optional[datetime] = None) -> float:
    """Capital más el interés devengado de forma lineal hasta el vencimiento."""
    now = now or datetime.now(timezone.utc)
    inicio, fin = _aware(bond.fecha_inicio), _aware(bond.fecha_vencimiento)
    total = (fin - inicio).total_seconds()
    progreso = 1.0 if total <= 0 else min(max((now - inicio).total_seconds() / total, 0.0), 1.0)
    return bond.monto_invertido * (1 + bond.tasa_interes * progreso)


def calcular_patrimonio(db: Session, account: Account) -> dict:
    """Valora una cuenta de inversión: saldo + bonos activos + posiciones de mercado activas."""
    now = datetime.now(timezone.utc)
    bonos = db.scalars(
        select(Bond).where(Bond.usuario_id == account.usuario_id, Bond.estado == BondStatus.ACTIVO)
    ).all()
    posiciones = db.scalars(
        select(UserInvestment).where(
            UserInvestment.usuario_id == account.usuario_id,
            UserInvestment.estado == InvestmentStatus.ACTIVA,
        )
    ).all()

    valor_bonos = sum(bond_value(b, now) for b in bonos)
    valor_inversiones = 0.0
    for pos in posiciones:
        if pos.participaciones is not None and pos.producto is not None:
            valor_inversiones += pos.participaciones * pos.producto.precio_actual_kidos
        else:
            valor_inversiones += pos.monto_invertido_kidos

    valor_bonos, valor_inversiones = round(valor_bonos, 2), round(valor_inversiones, 2)
    return {
        "valor_bonos": valor_bonos,
        "valor_inversiones": valor_inversiones,
        "patrimonio_total": round(account.saldo + valor_bonos + valor_inversiones, 2),
    }


def account_to_response(db: Session, account: Account) -> AccountResponse:
    response = AccountResponse.model_validate(account)
    if account.tipo == AccountType.INVERSION:
        for key, value in calcular_patrimonio(db, account).items():
            setattr(response, key, value)
    return response
