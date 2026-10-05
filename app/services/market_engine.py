"""Motor periódico de la economía familiar: bolsa simulada e inflación semanal.

Ambos procesos funcionan por "cursor temporal" (última simulación / última aplicación),
de modo que son idempotentes y recuperan los periodos perdidos si el servidor estuvo parado.
"""
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economy import InflationPolicy
from app.models.investment import InvestmentProduct, InvestmentType
from app.models.market import MarketItem, MarketStatus
from app.models.account import Account, AccountType
from app.models.transaction import Transaction, TransactionStatus, TransactionType

WEEK = timedelta(days=7)
WEEKS_PER_YEAR = 52
MIN_PRICE = 0.01

# Régimen bajista: de vez en cuando arranca una racha de 1 a 5 semanas (hasta ~un mes)
# en la que el activo solo baja.
BEAR_START_PROB = 0.05
BEAR_MIN_WEEKS = 1
BEAR_MAX_WEEKS = 5
BEAR_MIN_DROP = 0.005
_AVG_BEAR_LEN = (BEAR_MIN_WEEKS + BEAR_MAX_WEEKS) / 2
_BEAR_FRACTION = BEAR_START_PROB * _AVG_BEAR_LEN / (1 + BEAR_START_PROB * _AVG_BEAR_LEN)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def step_price(
    price: float,
    annual_return: float,
    sigma: float,
    bear_weeks_left: int,
    rng: random.Random,
) -> Tuple[float, int, bool]:
    """
    Avanza una semana. Devuelve (nuevo_precio, semanas_bajistas_restantes, fue_semana_bajista).

    Semana normal: movimiento browniano geométrico con deriva alcista.
    Semana bajista: el rendimiento es siempre negativo.
    La deriva de las semanas normales compensa las bajistas para que, a largo plazo,
    el rendimiento esperado sea `annual_return` (sesgo alcista moderado).
    """
    if bear_weeks_left <= 0 and rng.random() < BEAR_START_PROB:
        bear_weeks_left = rng.randint(BEAR_MIN_WEEKS, BEAR_MAX_WEEKS)

    z = rng.gauss(0.0, 1.0)
    if bear_weeks_left > 0:
        log_return = -(abs(z) * sigma + BEAR_MIN_DROP)
        bear_weeks_left -= 1
        was_bear = True
    else:
        mu_total = annual_return / WEEKS_PER_YEAR
        expected_bear = -(sigma * math.sqrt(2 / math.pi) + BEAR_MIN_DROP)
        mu_normal = (mu_total - _BEAR_FRACTION * expected_bear) / (1 - _BEAR_FRACTION)
        log_return = (mu_normal - 0.5 * sigma ** 2) + sigma * z
        was_bear = False

    return max(price * math.exp(log_return), MIN_PRICE), bear_weeks_left, was_bear


def run_market_updates(db: Session, now: Optional[datetime] = None, rng: Optional[random.Random] = None) -> int:
    """Simula las semanas completas transcurridas de cada índice. Devuelve nº de activos actualizados."""
    now = now or datetime.now(timezone.utc)
    rng = rng or random.Random()
    stmt = (
        select(InvestmentProduct)
        .where(InvestmentProduct.activo.is_(True))
        .where(InvestmentProduct.tipo == InvestmentType.INDICE)
        .with_for_update()
    )
    updated = 0
    for product in db.scalars(stmt).all():
        last = as_utc(product.ultima_simulacion or product.updated_at)
        weeks = int((now - last) / WEEK)
        if weeks <= 0:
            continue

        price = product.precio_actual_kidos
        bear_left = product.semanas_bajistas_restantes
        for _ in range(weeks):
            price, bear_left, _ = step_price(price, product.tasa_rentabilidad, product.volatilidad, bear_left, rng)

        product.precio_actual_kidos = round(price, 2)
        product.semanas_bajistas_restantes = bear_left
        product.variacion_pct = round((product.precio_actual_kidos / product.precio_base - 1) * 100, 2)
        product.ultima_simulacion = last + weeks * WEEK
        product.updated_at = now
        updated += 1
    return updated


def apply_news_shock(product: InvestmentProduct, impacto_pct: float, now: Optional[datetime] = None) -> Tuple[float, float]:
    """
    La noticia desplaza el precio actual `impacto_pct` puntos sobre el precio base y el modelo
    estocástico continúa desde ahí: +10% seguido de una noticia de -5% deja el activo en +5%.
    """
    now = now or datetime.now(timezone.utc)
    previous_price = product.precio_actual_kidos
    shifted = previous_price + product.precio_base * impacto_pct / 100.0
    product.precio_actual_kidos = round(max(shifted, MIN_PRICE), 2)
    product.variacion_pct = round((product.precio_actual_kidos / product.precio_base - 1) * 100, 2)
    product.updated_at = now
    return previous_price, product.precio_actual_kidos


def run_inflation(db: Session, now: Optional[datetime] = None) -> Tuple[int, int]:
    """Aplica la inflación por cada año completo transcurrido. Devuelve (años_aplicados, items_actualizados)."""
    now = now or datetime.now(timezone.utc)
    policy = db.scalars(select(InflationPolicy).order_by(InflationPolicy.id.desc()).with_for_update()).first()
    if not policy or not policy.activa:
        return 0, 0

    last = as_utc(policy.ultima_aplicacion)
    weeks = int((now - last) / WEEK)
    if weeks <= 0:
        return 0, 0

    factor = (1 + policy.tasa_semanal) ** weeks
    items = db.scalars(select(MarketItem).where(MarketItem.estado == MarketStatus.DISPONIBLE)).all()
    for item in items:
        item.precio_kidos = round(item.precio_kidos * factor, 2)

    policy.ultima_aplicacion = last + weeks * WEEK
    return weeks, len(items)


def run_savings_interest(db: Session, now: Optional[datetime] = None) -> Tuple[int, float, int]:
    """Capitaliza semanalmente las cuentas de ahorro y recupera semanas sin servicio."""
    now = now or datetime.now(timezone.utc)
    stmt = select(Account).where(Account.tipo == AccountType.AHORRO).with_for_update()
    accounts = db.scalars(stmt).all()
    paid_accounts = 0
    total_interest = 0.0
    periods_applied = 0

    for account in accounts:
        last = as_utc(account.ultimo_abono_interes or account.fecha_creacion)
        weeks = int((now - last) / WEEK)
        if weeks <= 0:
            continue

        periods_applied = max(periods_applied, weeks)
        interest = round(account.saldo * ((1 + account.tasa_interes) ** weeks - 1), 2)
        if interest > 0:
            account.saldo += interest
            db.add(
                Transaction(
                    cuenta_origen_id=None,
                    cuenta_destino_id=account.id,
                    monto=interest,
                    concepto=f"Interés de ahorro ({weeks} semana(s))",
                    tipo=TransactionType.INTERES,
                    estado=TransactionStatus.COMPLETADA,
                )
            )
            paid_accounts += 1
            total_interest += interest
        account.ultimo_abono_interes = last + weeks * WEEK

    return paid_accounts, round(total_interest, 2), periods_applied


def run_periodic_jobs(
    db: Session,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, int | float]:
    now = now or datetime.now(timezone.utc)
    productos = run_market_updates(db, now, rng)
    inflation_weeks, items = run_inflation(db, now)
    interest_accounts, interest_paid, interest_weeks = run_savings_interest(db, now)
    db.commit()
    return {
        "productos_simulados": productos,
        "semanas_inflacion_aplicadas": inflation_weeks,
        "items_actualizados": items,
        "cuentas_ahorro_abonadas": interest_accounts,
        "intereses_abonados": interest_paid,
        "semanas_interes_aplicadas": interest_weeks,
    }
