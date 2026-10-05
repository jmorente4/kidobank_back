from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import create_access_token, verify_password, verify_pin
from app.models.user import User, UserRole
from app.models.qr_card import QrCard
from app.schemas.auth import (
    ParentLoginRequest,
    PinLoginRequest,
    TokenResponse,
    UserAuthSummary,
)

router = APIRouter()

MAX_FAILED_ATTEMPTS = 3
LOCKOUT_MINUTES = 15


@router.post(
    "/login/parent",
    response_model=TokenResponse,
    summary="Inicio de sesión para Padres (email y contraseña)",
)
def login_parent(
    payload: ParentLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Autentica a un usuario con rol PADRE utilizando su correo electrónico y contraseña.
    """
    stmt = select(User).where(User.email == payload.email)
    user = db.scalars(stmt).first()

    if not user or user.rol != UserRole.PADRE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas o el usuario no es un Padre",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Comprobar si la cuenta está bloqueada por reintento de PIN
    now_utc = datetime.now(timezone.utc)
    if user.bloqueado_hasta and user.bloqueado_hasta > now_utc:
        minutos_restantes = int((user.bloqueado_hasta - now_utc).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada temporalmente. Inténtalo de nuevo en {minutos_restantes} minuto(s).",
        )

    # Validar contraseña/PIN
    if not verify_password(payload.password, user.pin_hash) and not verify_pin(payload.password, user.pin_hash):
        user.intentos_fallidos += 1
        if user.intentos_fallidos >= MAX_FAILED_ATTEMPTS:
            user.bloqueado_hasta = now_utc + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Restablecer reintentos al tener éxito
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.commit()

    token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserAuthSummary.model_validate(user),
    )


@router.post(
    "/login/pin",
    response_model=TokenResponse,
    summary="Inicio de sesión infantil o rápido mediante PIN numérico o QR",
)
def login_pin(
    payload: PinLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Permite el acceso a niños o padres seleccionando su avatar (`user_id`) o escaneando su tarjeta QR (`qr_uuid`).
    Aplica bloqueo automático tras 3 intentos fallidos consecutivos.
    """
    if not payload.user_id and not payload.qr_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar user_id o qr_uuid para iniciar sesión.",
        )

    user: Optional[User] = None

    if payload.qr_uuid:
        stmt = select(User).where(User.qr_uuid == payload.qr_uuid)
        user = db.scalars(stmt).first()
        if not user:
            stmt = (
                select(User)
                .join(QrCard, QrCard.usuario_id == User.id)
                .where(QrCard.qr_uuid == payload.qr_uuid, QrCard.activa.is_(True))
            )
            user = db.scalars(stmt).first()
    elif payload.user_id:
        user = db.get(User, payload.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    now_utc = datetime.now(timezone.utc)

    # Comprobar si la cuenta está bloqueada
    if user.bloqueado_hasta and user.bloqueado_hasta > now_utc:
        minutos_restantes = int((user.bloqueado_hasta - now_utc).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada por seguridad tras fallar {MAX_FAILED_ATTEMPTS} veces el PIN. Inténtalo de nuevo en {minutos_restantes} minuto(s).",
        )

    # Verificar el PIN numérico
    if not verify_pin(payload.pin, user.pin_hash):
        user.intentos_fallidos += 1
        if user.intentos_fallidos >= MAX_FAILED_ATTEMPTS:
            user.bloqueado_hasta = now_utc + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PIN incorrecto. Has superado los {MAX_FAILED_ATTEMPTS} intentos. Cuenta bloqueada durante {LOCKOUT_MINUTES} minutos.",
            )

        db.commit()
        intentos_restantes = MAX_FAILED_ATTEMPTS - user.intentos_fallidos
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"PIN incorrecto. Te quedan {intentos_restantes} intento(s).",
        )

    # Resetear contador de fallos tras login exitoso
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.commit()

    token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserAuthSummary.model_validate(user),
    )