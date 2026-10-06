from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.api.deps import (
    can_access_user,
    get_db,
    get_current_user,
    get_current_parent,
    get_family_user_ids,
)
from app.models.account import Account
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import MEMBER_ROLES, User
from app.schemas.transaction import TransactionResponse, TransactionCreate


router = APIRouter()


class PagaRequest(BaseModel):
    cuenta_destino_id: int = Field(..., description="ID de la cuenta del niño que recibe la paga")
    cuenta_origen_id: Optional[int] = Field(
        None, description="ID de la cuenta del padre (opcional si es emisión/subvención directa)"
    )
    monto: float = Field(..., gt=0, description="Monto en Kidos a abonar")
    concepto: Optional[str] = Field(default="Paga habitual", max_length=255)


class DepositoRequest(BaseModel):
    cuenta_destino_id: int = Field(..., description="ID de la cuenta propia del padre que se recarga")
    monto: float = Field(..., gt=0, description="Monto en Kidos a ingresar")
    concepto: str = Field(default="Recarga", min_length=1, max_length=255)


@router.post(
    "/deposito",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingresar fondos en una cuenta propia del padre",
)
def crear_deposito(
    payload: DepositoRequest,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    cuenta = db.scalars(
        select(Account).where(Account.id == payload.cuenta_destino_id).with_for_update()
    ).first()
    if cuenta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta no existe")
    if cuenta.usuario_id != current_parent.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes ingresar fondos en tus propias cuentas",
        )

    try:
        cuenta.saldo += payload.monto
        deposito = Transaction(
            cuenta_origen_id=None,
            cuenta_destino_id=cuenta.id,
            monto=payload.monto,
            concepto=payload.concepto,
            tipo=TransactionType.DEPOSITO,
            estado=TransactionStatus.COMPLETADA,
        )
        db.add(deposito)
        db.commit()
        db.refresh(deposito)
        return deposito
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error procesando el depósito",
        )


@router.get("/", response_model=List[TransactionResponse], summary="Listar todas las transacciones")
def listar_transacciones(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista todas las transacciones. Si es padre puede ver todas; si es niño, se pueden filtrar o restringir.
    """
    stmt_accounts = select(Account.id).where(Account.usuario_id.in_(get_family_user_ids(current_user, db)))
    account_ids = db.scalars(stmt_accounts).all()
    if not account_ids:
        return []
    stmt = (
        select(Transaction)
        .where(
            or_(
                Transaction.cuenta_origen_id.in_(account_ids),
                Transaction.cuenta_destino_id.in_(account_ids),
            )
        )
        .order_by(Transaction.fecha.desc())
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(stmt).all()


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED, summary="Realizar una transferencia entre cuentas")
def crear_transferencia(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Realiza una transferencia de fondos entre dos cuentas con validación de saldo.
    """
    # 1. Validar que la cuenta de origen existe y bloquear para actualización atómica
    stmt_origen = select(Account).where(Account.id == payload.cuenta_origen_id).with_for_update()
    cuenta_origen = db.scalars(stmt_origen).first()

    if not cuenta_origen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de origen no existe",
        )

    # 2. Validar que el usuario actual es dueño de la cuenta origen o es Padre
    owner_origen = db.get(User, cuenta_origen.usuario_id)
    if owner_origen is None or not can_access_user(current_user, owner_origen):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos sobre la cuenta de origen seleccionada",
        )

    # 3. Validar que la cuenta de destino existe
    stmt_destino = select(Account).where(Account.id == payload.cuenta_destino_id).with_for_update()
    cuenta_destino = db.scalars(stmt_destino).first()

    if not cuenta_destino:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de destino no existe",
        )
    destino = db.get(User, cuenta_destino.usuario_id)
    if destino is None or not can_access_user(current_user, destino):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos sobre la cuenta de destino seleccionada",
        )

    # 4. Validar saldo suficiente en la cuenta de origen
    if cuenta_origen.saldo < payload.monto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saldo insuficiente en la cuenta de origen. Disponible: {cuenta_origen.saldo:.2f} Kidos",
        )

    try:
        # 5. Actualizar saldos y registrar la transacción
        cuenta_origen.saldo -= payload.monto
        cuenta_destino.saldo += payload.monto

        nueva_transaccion = Transaction(
            cuenta_origen_id=cuenta_origen.id,
            cuenta_destino_id=cuenta_destino.id,
            monto=payload.monto,
            concepto=payload.concepto or "Transferencia entre cuentas",
            tipo=TransactionType.TRANSFERENCIA,
            estado=TransactionStatus.COMPLETADA,
        )

        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        return nueva_transaccion

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error procesando la transferencia",
        )


@router.get("/me", response_model=List[TransactionResponse], summary="Historial de movimientos del usuario actual")
def get_my_transactions(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Obtiene el historial de transacciones asociadas a todas las cuentas del usuario autenticado.
    """
    stmt_accounts = select(Account.id).where(Account.usuario_id == current_user.id)
    account_ids = db.scalars(stmt_accounts).all()

    if not account_ids:
        return []

    stmt = (
        select(Transaction)
        .where(
            or_(
                Transaction.cuenta_origen_id.in_(account_ids),
                Transaction.cuenta_destino_id.in_(account_ids),
            )
        )
        .order_by(Transaction.fecha.desc())
        .offset(offset)
        .limit(limit)
    )

    transactions = db.scalars(stmt).all()
    return transactions


@router.get(
    "/account/{account_id}",
    response_model=List[TransactionResponse],
    summary="Historial de movimientos de una cuenta específica",
)
def get_account_transactions(
    account_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Obtiene las transacciones de una cuenta específica por su ID.
    Los niños solo pueden ver el historial de sus propias cuentas; los padres pueden ver cualquier cuenta.
    """
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta especificada no existe",
        )

    owner = db.get(User, account.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver el historial de esta cuenta",
        )

    stmt = (
        select(Transaction)
        .where(
            or_(
                Transaction.cuenta_origen_id == account_id,
                Transaction.cuenta_destino_id == account_id,
            )
        )
        .order_by(Transaction.fecha.desc())
        .offset(offset)
        .limit(limit)
    )

    transactions = db.scalars(stmt).all()
    return transactions


@router.get(
    "/user/{user_id}",
    response_model=List[TransactionResponse],
    summary="Historial de movimientos de un usuario de la familia",
)
def get_user_transactions(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe")
    if not can_access_user(current_user, target_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a sus movimientos")

    account_ids = db.scalars(select(Account.id).where(Account.usuario_id == user_id)).all()
    if not account_ids:
        return []
    stmt = (
        select(Transaction)
        .where(
            or_(
                Transaction.cuenta_origen_id.in_(account_ids),
                Transaction.cuenta_destino_id.in_(account_ids),
            )
        )
        .order_by(Transaction.fecha.desc())
        .offset(offset)
        .limit(limit)
    )
    return db.scalars(stmt).all()


@router.post(
    "/paga",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Abonar la paga a la cuenta de un niño",
)
def abonar_paga(
    payload: PagaRequest,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    """
    Permite a PADRE/MADRE abonar la paga a NINO/FAMILIAR de su familia.
    """
    stmt_destino = select(Account).where(Account.id == payload.cuenta_destino_id).with_for_update()
    cuenta_destino = db.scalars(stmt_destino).first()

    if not cuenta_destino:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de destino no existe",
        )

    dueno_destino = db.get(User, cuenta_destino.usuario_id)
    if (
        not dueno_destino
        or dueno_destino.rol not in MEMBER_ROLES
        or not can_access_user(current_parent, dueno_destino)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La paga solo puede abonarse a NINO/FAMILIAR de tu familia",
        )

    cuenta_origen = None
    if payload.cuenta_origen_id:
        stmt_origen = select(Account).where(Account.id == payload.cuenta_origen_id).with_for_update()
        cuenta_origen = db.scalars(stmt_origen).first()

        if not cuenta_origen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La cuenta de origen especificada no existe",
            )

        if cuenta_origen.usuario_id != current_parent.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos sobre la cuenta de origen seleccionada",
            )

        if cuenta_origen.saldo < payload.monto:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Saldo insuficiente en la cuenta del padre. Disponible: {cuenta_origen.saldo:.2f} Kidos",
            )

    try:
        if cuenta_origen:
            cuenta_origen.saldo -= payload.monto

        cuenta_destino.saldo += payload.monto

        nueva_paga = Transaction(
            cuenta_origen_id=cuenta_origen.id if cuenta_origen else None,
            cuenta_destino_id=cuenta_destino.id,
            monto=payload.monto,
            concepto=payload.concepto or "Paga habitual",
            tipo=TransactionType.PAGA,
            estado=TransactionStatus.COMPLETADA,
        )

        db.add(nueva_paga)
        db.commit()
        db.refresh(nueva_paga)

        return nueva_paga

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error procesando el abono de la paga",
        )