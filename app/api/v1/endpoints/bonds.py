from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.account import Account
from app.models.bond import Bond, BondStatus
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User, UserRole
from app.schemas.bond import BondCreate, BondResponse

router = APIRouter()


@router.post("/", response_model=BondResponse, status_code=status.HTTP_201_CREATED, summary="Comprar un bono de renta fija")
def create_bond(
    bond_in: BondCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permite a un usuario (o a un padre en nombre de su hijo) comprar un bono de renta fija.
    Se descuenta el monto invertido de la cuenta de origen seleccionada.
    """
    # 1. Obtener y bloquear la cuenta de origen para evitar race conditions
    stmt_cuenta = select(Account).where(Account.id == bond_in.cuenta_origen_id).with_for_update()
    cuenta = db.scalars(stmt_cuenta).first()

    if not cuenta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de origen especificada no existe",
        )

    # 2. Validar propiedad (el dueño de la cuenta debe ser el usuario actual, o el usuario actual debe ser PADRE)
    if current_user.rol != UserRole.PADRE and cuenta.usuario_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes autorización para usar esta cuenta",
        )

    # 3. Validar saldo suficiente
    if cuenta.saldo < bond_in.monto_invertido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saldo insuficiente en la cuenta. Disponible: {cuenta.saldo:.2f} Kidos",
        )

    try:
        # 4. Descontar saldo y registrar transacción de inversión
        cuenta.saldo -= bond_in.monto_invertido

        transaccion = Transaction(
            cuenta_origen_id=cuenta.id,
            cuenta_destino_id=None,
            monto=bond_in.monto_invertido,
            concepto=f"Compra de Bono: {bond_in.titulo}",
            tipo="INVERSION",
            estado=TransactionStatus.COMPLETADA,
        )
        db.add(transaccion)

        # 5. Calcular fecha de vencimiento (compatible con SQLite y PostgreSQL)
        ahora = datetime.utcnow()
        fecha_vencimiento = ahora + timedelta(days=bond_in.plazo_dias)

        # 6. Crear el Bono
        nuevo_bono = Bond(
            usuario_id=cuenta.usuario_id,
            cuenta_origen_id=cuenta.id,
            titulo=bond_in.titulo,
            monto_invertido=bond_in.monto_invertido,
            tasa_interes=bond_in.tasa_interes,
            plazo_dias=bond_in.plazo_dias,
            fecha_inicio=ahora,
            fecha_vencimiento=fecha_vencimiento,
            estado=BondStatus.ACTIVO,
            penalizacion_aplicada=0.0,
        )

        db.add(nuevo_bono)
        db.commit()
        db.refresh(nuevo_bono)
        return nuevo_bono

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar la compra del bono: {str(e)}",
        )


@router.get("/", response_model=List[BondResponse], summary="Listar bonos del usuario")
def list_bonds(
    usuario_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista los bonos de renta fija. Si es PADRE puede consultar los de cualquier hijo filtrando por usuario_id.
    Si es NINO, solo puede ver sus propios bonos.
    """
    target_user_id = current_user.id
    if current_user.rol == UserRole.PADRE and usuario_id:
        target_user_id = usuario_id
    elif current_user.rol == UserRole.NINO and usuario_id and usuario_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver los bonos de otros usuarios",
        )

    stmt = select(Bond).where(Bond.usuario_id == target_user_id)
    bonos = db.scalars(stmt).all()
    return bonos


@router.post("/{bond_id}/redeem", response_model=BondResponse, summary="Rescatar o cobrar un bono")
def redeem_bond(
    bond_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Rescata un bono de renta fija.
    - Si ha llegado a la fecha de vencimiento: Estado COMPLETADO, se devuelve capital + intereses completos.
    - Si es antes de tiempo: Estado RESCATADO, se aplica una penalización.
    """
    stmt_bono = select(Bond).where(Bond.id == bond_id).with_for_update()
    bono = db.scalars(stmt_bono).first()

    if not bono:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El bono especificado no existe",
        )

    if current_user.rol != UserRole.PADRE and bono.usuario_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar este bono",
        )

    if bono.estado != BondStatus.ACTIVO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El bono ya no se encuentra activo (Estado actual: {bono.estado})",
        )

    # Obtener la cuenta de origen asociada
    cuenta = db.get(Account, bono.cuenta_origen_id)
    if not cuenta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de origen asociada al bono ya no existe",
        )

    ahora = datetime.utcnow()
    es_vencido = ahora >= bono.fecha_vencimiento

    try:
        if es_vencido:
            # Caso 1: Vencimiento exitoso -> Capital + Intereses
            interes_ganado = bono.monto_invertido * bono.tasa_interes
            monto_total_devuelto = bono.monto_invertido + interes_ganado
            bono.estado = BondStatus.COMPLETADO
            bono.penalizacion_aplicada = 0.0
            concepto_tx = f"Liquidación por vencimiento de Bono: {bono.titulo}"
        else:
            # Caso 2: Rescate anticipado -> Penalización (se devuelve solo el principal sin intereses)
            monto_total_devuelto = bono.monto_invertido
            interes_perdido = bono.monto_invertido * bono.tasa_interes
            bono.estado = BondStatus.RESCATADO
            bono.penalizacion_aplicada = interes_perdido
            concepto_tx = f"Rescate anticipado de Bono (con penalización): {bono.titulo}"

        # Devolver fondos a la cuenta
        cuenta.saldo += monto_total_devuelto

        # Registrar transacción de reembolso
        transaccion = Transaction(
            cuenta_origen_id=None,
            cuenta_destino_id=cuenta.id,
            monto=monto_total_devuelto,
            concepto=concepto_tx,
            tipo="TRANSFERENCIA",
            estado=TransactionStatus.COMPLETADA,
        )
        db.add(transaccion)

        db.commit()
        db.refresh(bono)
        return bono

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar el rescate del bono",
        )