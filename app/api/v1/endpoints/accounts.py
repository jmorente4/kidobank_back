from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_db, get_current_user
from app.models.account import Account, AccountType
from app.models.bond import Bond
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User, UserRole
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate, TransferRequest
from app.schemas.transaction import TransactionResponse
from app.services.patrimonio import account_to_response

router = APIRouter()


@router.get("/me", response_model=List[AccountResponse], summary="Obtener cuentas del usuario actual")
def get_my_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Devuelve todas las cuentas (Corriente, Ahorro, Inversión) del usuario autenticado.
    """
    stmt = select(Account).where(Account.usuario_id == current_user.id)
    accounts = db.scalars(stmt).all()
    return [account_to_response(db, a) for a in accounts]


@router.get("/user/{user_id}", response_model=List[AccountResponse], summary="Obtener cuentas de un usuario")
def get_accounts_by_user_id(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Consulta las cuentas de un usuario específico.
    Un usuario Niño solo puede consultar sus propias cuentas; los Padres pueden consultar cualquier cuenta.
    """
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario especificado no existe")
    if not can_access_user(current_user, target_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver las cuentas de este usuario",
        )

    stmt = select(Account).where(Account.usuario_id == user_id)
    accounts = db.scalars(stmt).all()
    return [account_to_response(db, a) for a in accounts]


@router.get("/{account_id}", response_model=AccountResponse, summary="Obtener detalle de una cuenta por ID")
def get_account_detail(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Obtiene la información detallada de una cuenta bancaria por su ID.
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
            detail="No tienes permiso para acceder a esta cuenta",
        )

    return account_to_response(db, account)


@router.patch("/{account_id}", response_model=AccountResponse, summary="Renombrar una cuenta")
def update_account(
    account_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta especificada no existe")
    owner = db.get(User, account.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar esta cuenta",
        )

    duplicate = db.scalars(
        select(Account.id).where(
            Account.usuario_id == account.usuario_id,
            Account.id != account.id,
            func.lower(Account.nombre) == payload.nombre.lower(),
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese nombre para este usuario",
        )

    account.nombre = payload.nombre
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese nombre para este usuario",
        ) from exc
    db.refresh(account)
    return account_to_response(db, account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar una cuenta sin saldo")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Solo los padres pueden eliminar cuentas (propias o de sus hijos) y únicamente si el saldo es 0."""
    if current_user.rol != UserRole.PADRE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los padres pueden eliminar cuentas bancarias",
        )
    account = db.scalars(select(Account).where(Account.id == account_id).with_for_update()).first()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta especificada no existe")
    owner = db.get(User, account.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar esta cuenta",
        )
    if account.saldo > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede eliminar: la cuenta aún tiene {account.saldo:.2f} Kidos.",
        )
    if db.scalars(select(Bond.id).where(Bond.cuenta_origen_id == account.id)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar: la cuenta tiene bonos asociados.",
        )
    try:
        db.delete(account)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo eliminar la cuenta",
        ) from exc


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED, summary="Crear una nueva cuenta")
def create_account(
    account_in: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Crea una nueva cuenta bancaria para un usuario. Solo los usuarios con rol PADRE pueden crear cuentas.
    """
    if current_user.rol != UserRole.PADRE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los padres pueden crear cuentas bancarias",
        )

    if account_in.tipo != AccountType.AHORRO and account_in.tasa_interes != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo las cuentas de ahorro pueden tener una tasa de interés",
        )

    # Verificar que la cuenta destino pertenezca al usuario autenticado o a su familia.
    target_user = db.get(User, account_in.usuario_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario especificado para la cuenta no existe",
        )
    if not can_access_user(current_user, target_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes crear cuentas para ti o para miembros de tu familia.",
        )

    saldo_inicial = 0.0 if target_user.id == current_user.id else account_in.saldo_inicial

    duplicate = db.scalars(
        select(Account.id).where(
            Account.usuario_id == target_user.id,
            func.lower(Account.nombre) == account_in.nombre.lower(),
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese nombre para este usuario",
        )

    new_account = Account(
        usuario_id=account_in.usuario_id,
        nombre=account_in.nombre,
        tipo=account_in.tipo,
        saldo=saldo_inicial,
        tasa_interes=account_in.tasa_interes,
    )

    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    return account_to_response(db, new_account)


@router.post("/transfer", response_model=TransactionResponse, summary="Realizar transferencia entre cuentas")
def transfer_kidos(
    transfer_in: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Efectúa una transferencia de Kidos entre dos cuentas.
    Valida saldos, propiedad de la cuenta de origen y realiza la transacción en un bloque atómico.
    """
    if transfer_in.monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto a transferir debe ser mayor a 0 Kidos",
        )

    if transfer_in.cuenta_origen_id == transfer_in.cuenta_destino_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cuenta de origen y destino no pueden ser la misma",
        )

    # Obtener las cuentas con bloqueo para evitar Race Conditions
    stmt_origen = select(Account).where(Account.id == transfer_in.cuenta_origen_id).with_for_update()
    cuenta_origen = db.scalars(stmt_origen).first()

    stmt_destino = select(Account).where(Account.id == transfer_in.cuenta_destino_id).with_for_update()
    cuenta_destino = db.scalars(stmt_destino).first()

    if not cuenta_origen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de origen no existe",
        )

    if not cuenta_destino:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de destino no existe",
        )

    # Verificar que el usuario que transfiere sea el dueño de la cuenta de origen o un Padre
    owner_origen = db.get(User, cuenta_origen.usuario_id)
    if owner_origen is None or not can_access_user(current_user, owner_origen):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes autorización para realizar transferencias desde esta cuenta",
        )

    owner_destino = db.get(User, cuenta_destino.usuario_id)
    if owner_destino is None or not can_access_user(current_user, owner_destino):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes autorización para transferir a esta cuenta",
        )

    # Verificar fondos suficientes
    if cuenta_origen.saldo < transfer_in.monto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saldo insuficiente. Saldo disponible: {cuenta_origen.saldo:.2f} Kidos",
        )

    try:
        # Operación atómica: Actualizar saldos
        cuenta_origen.saldo -= transfer_in.monto
        cuenta_destino.saldo += transfer_in.monto

        # Registrar la transacción
        nueva_transaccion = Transaction(
            cuenta_origen_id=cuenta_origen.id,
            cuenta_destino_id=cuenta_destino.id,
            monto=transfer_in.monto,
            concepto=transfer_in.concepto or "Transferencia entre cuentas",
            tipo=TransactionType.TRANSFERENCIA,
            estado=TransactionStatus.COMPLETADA,
        )

        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        return nueva_transaccion

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error procesando la transferencia bancaria",
        )
