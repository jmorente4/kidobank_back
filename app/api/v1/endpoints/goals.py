from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_current_user, get_db, get_family_user_ids
from app.models.account import Account
from app.models.goal import Goal
from app.models.user import User
from app.schemas.goal import GoalCreate, GoalDeposit, GoalResponse

router = APIRouter()


@router.get("/", response_model=List[GoalResponse], summary="Listar metas de ahorro")
def list_goals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Goal)
        .where(Goal.usuario_id.in_(get_family_user_ids(current_user, db)))
        .order_by(Goal.id.asc())
    )
    return db.scalars(stmt).all()


@router.post("/", response_model=GoalResponse, status_code=status.HTTP_201_CREATED, summary="Crear una meta de ahorro")
def create_goal(
    payload: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cuenta = db.get(Account, payload.cuenta_id)
    if not cuenta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta asociada a la meta no existe")

    owner = db.get(User, cuenta.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para crear una meta sobre esta cuenta")

    goal = Goal(
        usuario_id=cuenta.usuario_id,
        cuenta_id=cuenta.id,
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        monto_objetivo=payload.monto_objetivo,
        icono=payload.icono,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.post("/{goal_id}/deposit", response_model=GoalResponse, summary="Aportar dinero a una meta")
def deposit_goal(
    goal_id: int,
    payload: GoalDeposit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.get(Goal, goal_id)
    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La meta especificada no existe")

    owner = db.get(User, goal.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para aportar a esta meta")

    cuenta = db.get(Account, goal.cuenta_id)
    if not cuenta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta vinculada a la meta ya no existe")

    account_owner = db.get(User, cuenta.usuario_id)
    if account_owner is None or not can_access_user(current_user, account_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes aportar desde una cuenta ajena")

    if cuenta.saldo < payload.monto:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Saldo insuficiente en la cuenta. Disponible: {cuenta.saldo:.2f} Kidos")

    cuenta.saldo -= payload.monto
    goal.monto_actual += payload.monto
    if goal.monto_actual >= goal.monto_objetivo:
        goal.monto_actual = goal.monto_objetivo
        goal.estado = "COMPLETADA"

    db.commit()
    db.refresh(goal)
    return goal
