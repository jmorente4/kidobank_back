from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_current_parent, get_current_user, get_db
from app.models.account import Account, AccountType
from app.models.investment import InvestmentProduct, InvestmentStatus, InvestmentType, MarketNews, UserInvestment
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User, UserRole
from app.services.market_engine import apply_news_shock
from app.schemas.investment import (
    InvestmentProductCreate,
    InvestmentProductResponse,
    InvestmentPurchaseRequest,
    MarketNewsCreate,
    MarketNewsResponse,
    SellInvestmentRequest,
    SellInvestmentResponse,
    UserInvestmentResponse,
)
from app.services.market_engine import run_market_updates

router = APIRouter()

@router.get("/products", response_model=List[InvestmentProductResponse], summary="Listar activos de inversión")
def list_products(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(InvestmentProduct).where(InvestmentProduct.activo.is_(True)).order_by(InvestmentProduct.id.asc())
    return db.scalars(stmt).all()


@router.post("/products", response_model=InvestmentProductResponse, status_code=status.HTTP_201_CREATED, summary="Crear un activo de inversión")
def create_product(
    payload: InvestmentProductCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    existing = db.scalars(select(InvestmentProduct).where(InvestmentProduct.codigo == payload.codigo)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ya existe un activo con ese código")

    product = InvestmentProduct(
        nombre=payload.nombre,
        codigo=payload.codigo,
        tipo=payload.tipo,
        descripcion=payload.descripcion,
        precio_actual_kidos=payload.precio_actual_kidos,
        precio_base=payload.precio_actual_kidos,
        tasa_rentabilidad=payload.tasa_rentabilidad,
        duracion_dias=payload.duracion_dias,
        volatilidad=payload.volatilidad,
        variacion_pct=0.0,
        ultima_simulacion=datetime.now(timezone.utc),
        semanas_bajistas_restantes=0,
        activo=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products/{product_id}", response_model=InvestmentProductResponse, summary="Obtener detalle de un activo")
def get_product(
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = db.get(InvestmentProduct, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")
    return product


@router.post("/products/{product_id}/buy", response_model=UserInvestmentResponse, summary="Comprar un activo financiero simulado")
def buy_product(
    product_id: int,
    payload: InvestmentPurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = db.get(InvestmentProduct, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activo no encontrado")
    if not product.activo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este activo no está disponible")

    cuenta = db.get(Account, payload.cuenta_id)
    if not cuenta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta no existe")
    owner = db.get(User, cuenta.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta no pertenece al usuario autenticado ni a sus hijos")
    if cuenta.tipo != AccountType.CORRIENTE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La inversión debe hacerse desde una cuenta corriente")
    if cuenta.saldo < payload.monto_invertido_kidos:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Saldo insuficiente. Disponible: {cuenta.saldo:.2f} Kidos")

    cuenta.saldo -= payload.monto_invertido_kidos
    participaciones = payload.monto_invertido_kidos / product.precio_actual_kidos

    fecha_vencimiento = None
    if product.duracion_dias:
        fecha_vencimiento = datetime.now(timezone.utc) + timedelta(days=product.duracion_dias)

    investment = UserInvestment(
        usuario_id=cuenta.usuario_id,
        producto_id=product.id,
        monto_invertido_kidos=payload.monto_invertido_kidos,
        participaciones=participaciones,
        fecha_vencimiento=fecha_vencimiento,
        estado=InvestmentStatus.ACTIVA,
    )
    db.add(investment)
    db.add(
        Transaction(
            cuenta_origen_id=cuenta.id,
            cuenta_destino_id=None,
            monto=payload.monto_invertido_kidos,
            concepto=f"Compra de inversión: {product.nombre}",
            tipo=TransactionType.INVERSION,
            estado=TransactionStatus.COMPLETADA,
        )
    )
    db.commit()
    db.refresh(investment)
    return investment


@router.get("/news", response_model=List[MarketNewsResponse], summary="Listar noticias del mercado")
def list_market_news(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(MarketNews).where(MarketNews.activo.is_(True)).order_by(MarketNews.created_at.desc())
    return db.scalars(stmt).all()


@router.post("/news", response_model=MarketNewsResponse, status_code=status.HTTP_201_CREATED, summary="Crear una noticia del mercado")
def create_market_news(
    payload: MarketNewsCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    product = db.get(InvestmentProduct, payload.producto_id)
    if not product or product.tipo != InvestmentType.INDICE or not product.activo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Índice temático activo no encontrado")

    now = datetime.now(timezone.utc)
    run_market_updates(db, now=now)
    precio_anterior, precio_resultante = apply_news_shock(product, payload.impacto_pct, now=now)
    news = MarketNews(
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        impacto_pct=payload.impacto_pct,
        producto_id=product.id,
        precio_anterior=precio_anterior,
        precio_resultante=precio_resultante,
        activo=True,
    )
    db.add(news)
    db.commit()
    db.refresh(news)
    return news


@router.get("/positions/me", response_model=List[UserInvestmentResponse], summary="Mis posiciones de inversión")
def list_my_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(UserInvestment).where(UserInvestment.usuario_id == current_user.id).order_by(UserInvestment.id.desc())
    return db.scalars(stmt).all()


@router.post("/positions/{investment_id}/sell", response_model=SellInvestmentResponse, summary="Vender una posición al precio actual de mercado")
def sell_position(
    investment_id: int,
    payload: SellInvestmentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    investment = db.get(UserInvestment, investment_id)
    if not investment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inversión no encontrada")
    owner = db.get(User, investment.usuario_id)
    if owner is None or not can_access_user(current_user, owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso sobre esta inversión")
    if investment.estado != InvestmentStatus.ACTIVA:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La inversión ya no está activa")

    cuenta = db.get(Account, payload.cuenta_id)
    if not cuenta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta no existe")
    if cuenta.usuario_id != investment.usuario_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta debe pertenecer al dueño de la inversión")
    if cuenta.tipo != AccountType.CORRIENTE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El dinero debe ingresarse en una cuenta corriente")

    product = db.get(InvestmentProduct, investment.producto_id)
    monto_recibido = round((investment.participaciones or 0.0) * product.precio_actual_kidos, 2)

    cuenta.saldo += monto_recibido
    investment.estado = InvestmentStatus.LIQUIDADA
    db.add(
        Transaction(
            cuenta_origen_id=None,
            cuenta_destino_id=cuenta.id,
            monto=monto_recibido,
            concepto=f"Venta de inversión: {product.nombre}",
            tipo=TransactionType.INVERSION,
            estado=TransactionStatus.COMPLETADA,
        )
    )
    db.commit()

    return SellInvestmentResponse(
        inversion_id=investment.id,
        monto_invertido_kidos=investment.monto_invertido_kidos,
        monto_recibido_kidos=monto_recibido,
        resultado_kidos=round(monto_recibido - investment.monto_invertido_kidos, 2),
        estado=investment.estado,
    )
