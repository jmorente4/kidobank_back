from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_current_parent, get_current_user, get_db
from app.models.account import Account, AccountType
from app.models.bond import Bond, BondStatus
from app.models.economy import InflationPolicy, InflationPolicyStatus
from app.models.goal import Goal, GoalStatus
from app.models.investment import InvestmentProduct, InvestmentStatus, UserInvestment
from app.models.market import EscrowStatus, EscrowTransaction
from app.models.user import User, UserRole
from app.schemas.economy import (
    AccountSummary,
    InflationPolicyCreate,
    InflationPolicyResponse,
    SavingsRateResponse,
    SavingsRateUpdate,
    WealthSummary,
)
from app.services.market_engine import run_inflation, run_savings_interest

router = APIRouter()


def _latest_policy(db: Session) -> InflationPolicy | None:
    return db.scalars(select(InflationPolicy).order_by(InflationPolicy.id.desc())).first()


@router.get(
    "/inflation",
    response_model=InflationPolicyResponse | None,
    summary="Consultar la política semanal de inflación",
    description="Devuelve la política configurada o null si todavía no existe ninguna.",
)
def get_inflation_policy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _latest_policy(db)


@router.post("/inflation", response_model=InflationPolicyResponse, status_code=status.HTTP_201_CREATED, summary="Configurar la tasa semanal de inflación")
def create_inflation_policy(
    payload: InflationPolicyCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    if _latest_policy(db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una política de inflación; utiliza PATCH para modificarla")

    policy = InflationPolicy(
        nombre=payload.nombre,
        tasa_semanal=payload.tasa_semanal,
        activa=True,
        estado=InflationPolicyStatus.ACTIVA,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


@router.patch("/inflation", response_model=InflationPolicyResponse, summary="Cambiar la tasa semanal de inflación")
def update_inflation_policy(
    payload: InflationPolicyCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    policy = _latest_policy(db)
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe una política de inflación para actualizar")

    run_inflation(db)
    policy.nombre = payload.nombre
    policy.tasa_semanal = payload.tasa_semanal
    policy.activa = True
    policy.estado = InflationPolicyStatus.ACTIVA
    db.commit()
    db.refresh(policy)
    return policy


@router.patch("/savings-rate/{account_id}", response_model=SavingsRateResponse, summary="Fijar la tasa semanal de una cuenta de ahorro")
def update_savings_rate(
    account_id: int,
    payload: SavingsRateUpdate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
    owner = db.get(User, account.usuario_id)
    if owner is None or not can_access_user(current_parent, owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para configurar esta cuenta")
    if account.tipo != AccountType.AHORRO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tasa periódica solo se configura en cuentas de ahorro")

    run_savings_interest(db)
    account.tasa_interes = payload.tasa_semanal
    db.commit()
    return {"cuenta_id": account.id, "tasa_semanal": account.tasa_interes}


def _build_wealth_summary(user_id: int, db: Session) -> WealthSummary:
    policy = _latest_policy(db)
    inflation = policy.tasa_semanal if policy and policy.activa else 0.0

    accounts = db.scalars(select(Account).where(Account.usuario_id == user_id).order_by(Account.id.asc())).all()
    summaries: List[AccountSummary] = []
    balances = {kind: 0.0 for kind in AccountType}
    for account in accounts:
        balances[account.tipo] += account.saldo
        real_weekly = (1 + account.tasa_interes) / (1 + inflation) - 1
        summaries.append(
            AccountSummary(
                cuenta_id=account.id,
                tipo=account.tipo,
                saldo=account.saldo,
                tasa_nominal_periodo=account.tasa_interes,
                tasa_nominal_semanal=account.tasa_interes,
                tasa_real_semanal=round(real_weekly, 6),
            )
        )

    market_value = db.execute(
        select(func.coalesce(func.sum(UserInvestment.participaciones * InvestmentProduct.precio_actual_kidos), 0.0))
        .join(InvestmentProduct, InvestmentProduct.id == UserInvestment.producto_id)
        .where(UserInvestment.usuario_id == user_id, UserInvestment.estado == InvestmentStatus.ACTIVA)
    ).scalar_one()
    bond_value = db.execute(
        select(func.coalesce(func.sum(Bond.monto_invertido), 0.0))
        .where(Bond.usuario_id == user_id, Bond.estado == BondStatus.ACTIVO)
    ).scalar_one()
    goal_value = db.execute(
        select(func.coalesce(func.sum(Goal.monto_actual), 0.0))
        .where(Goal.usuario_id == user_id, Goal.estado != GoalStatus.PAUSADA)
    ).scalar_one()
    escrow_value = db.execute(
        select(func.coalesce(func.sum(EscrowTransaction.monto), 0.0))
        .where(EscrowTransaction.comprador_id == user_id, EscrowTransaction.estado == EscrowStatus.PENDIENTE)
    ).scalar_one()

    total = sum(balances.values()) + market_value + bond_value + goal_value + escrow_value
    return WealthSummary(
        usuario_id=user_id,
        cuentas=summaries,
        saldo_corriente=round(balances[AccountType.CORRIENTE], 2),
        saldo_ahorro=round(balances[AccountType.AHORRO], 2),
        saldo_cuentas_inversion=round(balances[AccountType.INVERSION], 2),
        valor_inversiones_mercado=round(market_value, 2),
        valor_bonos_activos=round(bond_value, 2),
        valor_metas_ahorro=round(goal_value, 2),
        fondos_en_escrow=round(escrow_value, 2),
        patrimonio_total=round(total, 2),
        inflacion_semanal=inflation,
    )


@router.get("/summary/me", response_model=WealthSummary, summary="Resumen de patrimonio del usuario actual")
def my_wealth_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build_wealth_summary(current_user.id, db)


@router.get("/summary/{user_id}", response_model=WealthSummary, summary="Resumen de patrimonio de un usuario")
def user_wealth_summary(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe")
    if not can_access_user(current_user, target_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver este patrimonio")
    return _build_wealth_summary(user_id, db)
