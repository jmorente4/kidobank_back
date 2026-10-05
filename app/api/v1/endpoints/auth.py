import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.deps import get_db
from app.core.security import create_access_token, get_password_hash, verify_password, verify_pin
from app.models.password_reset import PasswordResetToken
from app.models.user import User, UserRole
from app.models.qr_card import QrCard
from app.schemas.auth import (
    ParentLoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PinLoginRequest,
    TokenResponse,
    UserAuthSummary,
)
from app.services.password_reset import send_password_reset_email

router = APIRouter()

MAX_FAILED_ATTEMPTS = 3
LOCKOUT_MINUTES = 15


def _locked_until(user: User) -> Optional[datetime]:
    value = user.bloqueado_hasta
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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
    blocked_until = _locked_until(user)
    if blocked_until and blocked_until > now_utc:
        minutos_restantes = int((blocked_until - now_utc).total_seconds() / 60) + 1
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
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Solicitar un enlace de restablecimiento de contraseña",
)
def request_password_reset(
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperación de contraseña no está configurada en este entorno.",
        )

    user = db.scalars(
        select(User).where(User.email == payload.email, User.rol == UserRole.PADRE)
    ).first()
    if user:
        now = datetime.now(timezone.utc)
        db.query(PasswordResetToken).filter(
            PasswordResetToken.usuario_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": now}, synchronize_session=False)

        raw_token = secrets.token_urlsafe(32)
        token = PasswordResetToken(
            usuario_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(hours=1),
        )
        db.add(token)
        db.commit()

        separator = "&" if "?" in settings.PASSWORD_RESET_URL else "?"
        reset_url = f"{settings.PASSWORD_RESET_URL}{separator}token={quote(raw_token)}"
        background_tasks.add_task(
            send_password_reset_email, user.email, reset_url
        )

    return {"message": "Si el correo corresponde a una cuenta de adulto, recibirá instrucciones."}


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Restablecer una contraseña con un token válido",
)
def reset_password(
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    reset_token = db.scalars(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    ).first()
    now = datetime.now(timezone.utc)
    expires_at = reset_token.expires_at if reset_token else now
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not reset_token or reset_token.used_at is not None or expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace de restablecimiento no es válido o ha caducado.",
        )

    user = db.get(User, reset_token.usuario_id)
    if user is None or user.rol != UserRole.PADRE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace de restablecimiento no es válido o ha caducado.",
        )

    user.pin_hash = get_password_hash(payload.new_password)
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.query(PasswordResetToken).filter(
        PasswordResetToken.usuario_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.commit()


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
    blocked_until = _locked_until(user)
    if blocked_until and blocked_until > now_utc:
        minutos_restantes = int((blocked_until - now_utc).total_seconds() / 60) + 1
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