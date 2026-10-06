from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_family_admin_ids, get_current_parent, get_db, get_current_user
from app.models.account import Account
from app.models.bond import Bond, BondOffer, BondStatus
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import ADMIN_ROLES, MEMBER_ROLES, User
from app.schemas.bond import BondCreate, BondOfferCreate, BondOfferResponse, BondResponse

router = APIRouter()


@router.post(
    "/offers",
    response_model=BondOfferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publicar una oferta de bono familiar (PADRE/MADRE)",
)
def create_offer(
    offer_in: BondOfferCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    offer = BondOffer(
        padre_id=current_parent.id,
        titulo=offer_in.titulo.strip(),
        tasa_interes=offer_in.tasa_interes,
        plazo_dias=offer_in.plazo_dias,
        monto_minimo=offer_in.monto_minimo,
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


@router.get(
    "/offers",
    response_model=List[BondOfferResponse],
    summary="Listar ofertas de la familia; NINO/FAMILIAR solo ven las activas",
)
def list_offers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(BondOffer).order_by(BondOffer.id.desc())
    stmt = stmt.where(BondOffer.padre_id.in_(get_family_admin_ids(current_user, db)))
    if current_user.rol not in ADMIN_ROLES:
        stmt = stmt.where(BondOffer.activa.is_(True))
    return db.scalars(stmt).all()


@router.delete("/offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirar una oferta de la familia")
def delete_offer(
    offer_id: int,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    offer = db.get(BondOffer, offer_id)
    if offer is None or offer.padre_id not in get_family_admin_ids(current_parent, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La oferta no existe")
    db.delete(offer)
    db.commit()


@router.post("/", response_model=BondResponse, status_code=status.HTTP_201_CREATED, summary="Comprar una oferta de bono (NINO/FAMILIAR)")
def create_bond(
    bond_in: BondCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    El miembro compra una oferta familiar de renta fija, pagando con una cuenta propia.
    Las condiciones (título, tasa y plazo) las fija la oferta.
    """
    if current_user.rol not in MEMBER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo NINO/FAMILIAR pueden comprar bonos; PADRE/MADRE los publican",
        )

    offer = db.get(BondOffer, bond_in.oferta_id)
    if offer is None or not offer.activa or offer.padre_id not in get_family_admin_ids(current_user, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La oferta de bono no existe")
    if bond_in.monto_invertido < offer.monto_minimo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El importe mínimo de esta oferta es {offer.monto_minimo:.2f} Kidos",
        )

    # 1. Obtener y bloquear la cuenta de origen para evitar race conditions
    stmt_cuenta = select(Account).where(Account.id == bond_in.cuenta_origen_id).with_for_update()
    cuenta = db.scalars(stmt_cuenta).first()

    if not cuenta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cuenta de origen especificada no existe",
        )

    # 2. La cuenta debe ser del propio hijo
    if cuenta.usuario_id != current_user.id:
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
            concepto=f"Compra de Bono: {offer.titulo}",
            tipo="INVERSION",
            estado=TransactionStatus.COMPLETADA,
        )
        db.add(transaccion)

        # 5. Calcular fecha de vencimiento (compatible con SQLite y PostgreSQL)
        ahora = datetime.utcnow()
        fecha_vencimiento = ahora + timedelta(days=offer.plazo_dias)

        # 6. Crear el Bono
        nuevo_bono = Bond(
            usuario_id=cuenta.usuario_id,
            cuenta_origen_id=cuenta.id,
            titulo=offer.titulo,
            monto_invertido=bond_in.monto_invertido,
            tasa_interes=offer.tasa_interes,
            plazo_dias=offer.plazo_dias,
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
    target_user_id = usuario_id or current_user.id
    target_user = db.get(User, target_user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe")
    if not can_access_user(current_user, target_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para ver los bonos de este usuario")

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

    owner = db.get(User, bono.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
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