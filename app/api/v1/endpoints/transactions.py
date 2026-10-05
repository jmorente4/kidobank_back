from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, get_current_parent
from app.models.account import Account
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User, UserRole
from app.schemas.transaction import TransactionResponse, TransactionCreate


router = APIRouter()


class PagaRequest(BaseModel):
    cuenta_destino_id: int = Field(..., description="ID de la cuenta del niño que recibe la paga")
    cuenta_origen_id: Optional[int] = Field(
        None, description="ID de la cuenta del padre (opcional si es emisión/subvención directa)"
    )
    monto: float = Field(..., gt=0, description="Monto en Kidos a abonar")
    concepto: Optional[str] = Field(default="Paga habitual", max_length=255)


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
    if current_user.rol == UserRole.PADRE:
        stmt = select(Transaction).order_by(Transaction.fecha.desc()).offset(offset).limit(limit)
    else:
        # Si es un niño, devolvemos las transacciones asociadas a sus cuentas
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
    if current_user.rol != UserRole.PADRE and cuenta_origen.usuario_id != current_user.id:
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

    if current_user.rol != UserRole.PADRE and account.usuario_id != current_user.id:
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
    Permite exclusivamente a un usuario con rol PADRE abonar la paga a un niño.
    """
    stmt_destino = select(Account).where(Account.id == payload.cuenta_destino_id).with_for_update()
    cuenta_destino = db.scalars(stmt_destino).first()

    if not cuenta_destino:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de destino no existe",
        )

    dueno_destino = db.get(User, cuenta_destino.usuario_id)
    if not dueno_destino or dueno_destino.rol != UserRole.NINO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La paga solo puede ser abonada a una cuenta perteneciente a un usuario de rol NIÑO",
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