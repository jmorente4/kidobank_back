import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.deps import get_db
from app.core.security import create_access_token, get_password_hash, verify_password, verify_pin
from app.models.password_reset import PasswordResetToken
from app.models.user import ADMIN_ROLES, MEMBER_ROLES, User
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
from app.services.login_attempts import (
    check_lockout,
    lock_auth_user,
    record_failed_attempt,
)

router = APIRouter()

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

    if not user or user.rol not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas o el usuario no es PADRE/MADRE",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = lock_auth_user(db, user.id)
    now_utc = datetime.now(timezone.utc)
    check_lockout(user, now_utc)

    # Validar contraseña/PIN
    if not verify_password(payload.password, user.pin_hash) and not verify_pin(payload.password, user.pin_hash):
        record_failed_attempt(db, user, now_utc)

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
        select(User).where(User.email == payload.email, User.rol.in_(ADMIN_ROLES))
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
    if user is None or user.rol not in ADMIN_ROLES:
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
    summary="Inicio de sesión por PIN con apodo, ID o QR",
)
def login_pin(
    payload: PinLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Permite el acceso a niños o padres seleccionando su avatar (`user_id`) o escaneando su tarjeta QR (`qr_uuid`).
    Comparte el límite con el cambio de PIN: NINO/FAMILIAR se bloquean hasta que PADRE/MADRE los desbloqueen.
    """
    if payload.nombre_usuario is not None and (
        payload.user_id is not None or payload.qr_uuid is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usa nombre_usuario sin user_id ni qr_uuid.",
        )
    if not payload.user_id and not payload.qr_uuid and payload.nombre_usuario is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar nombre_usuario, user_id o qr_uuid para iniciar sesión.",
        )

    user: Optional[User] = None

    if payload.nombre_usuario is not None:
        user = db.scalar(select(User).where(
            func.lower(User.nombre_usuario) == payload.nombre_usuario,
            User.rol.in_(MEMBER_ROLES),
        ))
    elif payload.qr_uuid:
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

    user = lock_auth_user(db, user.id)
    now_utc = datetime.now(timezone.utc)
    check_lockout(user, now_utc)

    # Verificar el PIN numérico
    if not verify_pin(payload.pin, user.pin_hash):
        intentos_restantes = record_failed_attempt(db, user, now_utc)
        if intentos_restantes == 0:
            check_lockout(user, now_utc)

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