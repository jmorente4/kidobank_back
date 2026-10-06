from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_current_user, get_db, get_family_user_ids
from app.models.account import Account, AccountType
from app.models.market import EscrowStatus, EscrowTransaction, MarketItem, MarketStatus
from app.models.user import User, UserRole
from app.schemas.market import (
    EscrowResponse,
    MarketItemCreate,
    MarketItemResponse,
    MarketItemUpdate,
    PurchaseItemRequest,
)

router = APIRouter()


def _can_access_market_party(current_user: User, user_id: int, db: Session) -> bool:
    party = db.get(User, user_id)
    return party is not None and can_access_user(current_user, party)


@router.get("/items", response_model=List[MarketItemResponse], summary="Listar artículos del mercadillo")
def list_market_items(
    estado: Optional[MarketStatus] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(MarketItem)
    if estado:
        stmt = stmt.where(MarketItem.estado == estado)
    else:
        stmt = stmt.where(MarketItem.estado != MarketStatus.CANCELADO)
    stmt = stmt.order_by(MarketItem.created_at.desc())
    return db.scalars(stmt).all()


@router.get("/items/{item_id}", response_model=MarketItemResponse, summary="Obtener un artículo del mercadillo")
def get_market_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(MarketItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    return item


@router.post("/items", response_model=MarketItemResponse, status_code=status.HTTP_201_CREATED, summary="Publicar un artículo o servicio")
def create_market_item(
    payload: MarketItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = MarketItem(
        vendedor_id=current_user.id,
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        precio_kidos=payload.precio_kidos,
        estado=MarketStatus.DISPONIBLE,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/items/{item_id}", response_model=MarketItemResponse, summary="Actualizar un artículo propio")
def update_market_item(
    item_id: int,
    payload: MarketItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(MarketItem).where(MarketItem.id == item_id).with_for_update())
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    if not _can_access_market_party(current_user, item.vendedor_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes editar este artículo")
    if item.estado != MarketStatus.DISPONIBLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Solo puedes editar artículos disponibles")

    if payload.titulo is not None:
        item.titulo = payload.titulo
    if payload.descripcion is not None:
        item.descripcion = payload.descripcion
    if payload.precio_kidos is not None:
        item.precio_kidos = payload.precio_kidos

    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirar un artículo disponible conservando su historial",
)
def delete_market_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(MarketItem).where(MarketItem.id == item_id).with_for_update())
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    if not _can_access_market_party(current_user, item.vendedor_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes retirar este artículo")
    if item.estado == MarketStatus.CANCELADO:
        return
    if item.estado != MarketStatus.DISPONIBLE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Solo se pueden retirar artículos disponibles")
    item.estado = MarketStatus.CANCELADO
    db.commit()


@router.post("/items/{item_id}/buy", response_model=EscrowResponse, summary="Comprar un artículo y bloquear dinero en escrow")
def buy_market_item(
    item_id: int,
    payload: PurchaseItemRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(MarketItem).where(MarketItem.id == item_id).with_for_update())
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    if item.vendedor_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes comprar tu propio artículo")
    if item.estado != MarketStatus.DISPONIBLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este artículo ya no está disponible")

    cuenta = db.get(Account, payload.cuenta_id)
    if not cuenta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta de compra no existe")
    if cuenta.usuario_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta seleccionada no pertenece al usuario autenticado")
    if cuenta.tipo != AccountType.CORRIENTE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El dinero para comprar en el mercadillo debe bloquearse desde una cuenta corriente",
        )
    if cuenta.saldo < item.precio_kidos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saldo insuficiente en la cuenta corriente. Disponible: {cuenta.saldo:.2f} Kidos",
        )

    cuenta.saldo -= item.precio_kidos
    item.estado = MarketStatus.ESCROW
    item.comprador_id = current_user.id

    escrow = EscrowTransaction(
        item_id=item.id,
        comprador_id=current_user.id,
        vendedor_id=item.vendedor_id,
        monto=item.precio_kidos,
        estado=EscrowStatus.PENDIENTE,
    )
    db.add(escrow)
    db.commit()
    db.refresh(escrow)
    return escrow


@router.post("/items/{item_id}/confirm-delivery", response_model=EscrowResponse, summary="Confirmar entrega del artículo y liberar fondos al vendedor")
def confirm_market_delivery(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(MarketItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    if item.estado not in {MarketStatus.ESCROW, MarketStatus.VENDIDO}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay una transacción activa de escrow para este artículo")

    escrow = (
        db.query(EscrowTransaction)
        .filter(EscrowTransaction.item_id == item_id)
        .filter(EscrowTransaction.estado == EscrowStatus.PENDIENTE)
        .order_by(EscrowTransaction.created_at.desc())
        .first()
    )
    if not escrow:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No existe un escrow pendiente para este artículo")

    allowed_users = {escrow.comprador_id, escrow.vendedor_id}
    if current_user.id not in allowed_users and not any(
        _can_access_market_party(current_user, user_id, db) for user_id in allowed_users
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para confirmar la entrega")

    vendedor_account = (
        db.query(Account)
        .filter(Account.usuario_id == escrow.vendedor_id)
        .order_by(Account.tipo == AccountType.CORRIENTE, Account.id.asc())
        .first()
    )
    if not vendedor_account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El vendedor no tiene una cuenta asociada")

    vendedor_account.saldo += escrow.monto
    item.estado = MarketStatus.VENDIDO
    item.comprador_id = escrow.comprador_id
    escrow.estado = EscrowStatus.CONFIRMADO
    escrow.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(escrow)
    return escrow


@router.post("/items/{item_id}/cancel", response_model=EscrowResponse, summary="Cancelar compra y devolver el dinero al comprador")
def cancel_market_purchase(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(MarketItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    if item.estado != MarketStatus.ESCROW:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este artículo no se encuentra en una compra pendiente")

    escrow = (
        db.query(EscrowTransaction)
        .filter(EscrowTransaction.item_id == item_id)
        .filter(EscrowTransaction.estado == EscrowStatus.PENDIENTE)
        .order_by(EscrowTransaction.created_at.desc())
        .first()
    )
    if not escrow:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No existe un escrow pendiente para este artículo")

    allowed_users = {escrow.comprador_id, escrow.vendedor_id}
    if current_user.id not in allowed_users and not any(
        _can_access_market_party(current_user, user_id, db) for user_id in allowed_users
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes cancelar esta compra")

    comprador_account = (
        db.query(Account)
        .filter(Account.usuario_id == escrow.comprador_id)
        .order_by(Account.tipo == AccountType.CORRIENTE, Account.id.asc())
        .first()
    )
    if not comprador_account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El comprador no tiene una cuenta asociada")

    comprador_account.saldo += escrow.monto
    item.estado = MarketStatus.DISPONIBLE
    item.comprador_id = None
    escrow.estado = EscrowStatus.REEMBOLSADO
    escrow.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(escrow)
    return escrow


@router.get("/history", response_model=List[EscrowResponse], summary="Historial de transacciones del mercadillo")
def list_market_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    family_ids = get_family_user_ids(current_user, db)
    stmt = (
        select(EscrowTransaction)
        .where(
            EscrowTransaction.comprador_id.in_(family_ids)
            | EscrowTransaction.vendedor_id.in_(family_ids)
        )
        .order_by(EscrowTransaction.created_at.desc())
    )
    return db.scalars(stmt).all()
