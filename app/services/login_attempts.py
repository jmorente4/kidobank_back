from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole

MAX_FAILED_ATTEMPTS = 3
LOCKOUT_MINUTES = 15


def lock_auth_user(db: Session, user_id: int) -> User:
    # Refresh objects already loaded by authentication dependencies after acquiring the lock.
    return db.scalars(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def check_lockout(user: User, now: datetime) -> None:
    if user.bloqueado_por_pin or (
        user.rol == UserRole.NINO and user.intentos_fallidos >= MAX_FAILED_ATTEMPTS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta bloqueada por intentos de PIN. Tu padre debe desbloquearla.",
        )
    blocked_until = user.bloqueado_hasta
    if blocked_until is not None:
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        if blocked_until > now:
            seconds = max(1, int((blocked_until - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cuenta bloqueada por seguridad. Inténtalo de nuevo en {seconds // 60 + 1} minuto(s).",
                headers={"Retry-After": str(seconds)},
            )
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None


def record_failed_attempt(db: Session, user: User, now: datetime) -> int:
    user.intentos_fallidos += 1
    remaining = max(0, MAX_FAILED_ATTEMPTS - user.intentos_fallidos)
    if remaining == 0:
        if user.rol == UserRole.NINO:
            user.bloqueado_por_pin = True
            user.bloqueado_hasta = None
        else:
            user.bloqueado_hasta = now + timedelta(minutes=LOCKOUT_MINUTES)
    db.commit()
    return remaining
