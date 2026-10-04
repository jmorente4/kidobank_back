from datetime import datetime, timedelta, timezone
from typing import Union
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.deps import get_db
from app.core.security import create_access_token, verify_password, verify_pin
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    ParentLoginRequest,
    PinLoginRequest,
    TokenResponse,
    UserAuthSummary,
)

router = APIRouter()

MAX_PIN_ATTEMPTS = 3
LOCKOUT_MINUTES = 15


@router.post("/login", response_model=TokenResponse, summary="Inicio de sesión web (Padre o Niño)")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint unificado de inicio de sesión web.
    Permite autenticarse enviando:
    - **Email o Nombre de usuario** (`username`)
    - **Contraseña o PIN** (`password`)
    
    Funciona tanto para el Padre (vía email) como para el Niño (vía usuario/alias).
    """
    identifier = payload.username.strip()
    password = payload.password.strip()

    # Búsqueda por email o por nombre de usuario/alias
    user = db.query(User).filter(
        or_(
            User.email == identifier,
            User.nombre == identifier
        )
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Comprobación de bloqueo activo por intentos fallidos
    now = datetime.now(timezone.utc)
    if user.bloqueado_hasta and user.bloqueado_hasta > now:
        minutos_restantes = int((user.bloqueado_hasta - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada por seguridad. Inténtalo de nuevo en {minutos_restantes} minuto(s)."
        )

    # Verificación del hash de la contraseña/PIN
    if not verify_password(password, user.pin_hash):
        user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
        if user.intentos_fallidos >= MAX_PIN_ATTEMPTS:
            user.bloqueado_hasta = now + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Credenciales incorrectas. Se ha superado el máximo de intentos y la cuenta se ha bloqueado por {LOCKOUT_MINUTES} minutos."
            )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Credenciales válidas: reiniciar contadores de seguridad
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.commit()

    # Generar JWT
    role_str = user.rol.value if hasattr(user.rol, "value") else str(user.rol)
    access_token = create_access_token(subject=user.id, role=role_str)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserAuthSummary.model_validate(user)
    )


@router.post("/pin", response_model=TokenResponse, summary="Inicio de sesión rápido por PIN / QR (Niño)")
def login_with_pin(
    payload: PinLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Inicio de sesión rápido enfocado en los niños mediante PIN de 4 dígitos.
    Sombra la autenticación por selección directa de avatar (`user_id`) o por tarjeta QR escaneada (`qr_uuid`).
    """
    if not payload.user_id and not payload.qr_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe indicar 'user_id' o 'qr_uuid' para autenticarse por PIN."
        )

    if payload.user_id:
        user = db.query(User).filter(User.id == payload.user_id).first()
    else:
        user = db.query(User).filter(User.qr_uuid == payload.qr_uuid).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    now = datetime.now(timezone.utc)
    if user.bloqueado_hasta and user.bloqueado_hasta > now:
        minutos_restantes = int((user.bloqueado_hasta - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada temporalmente. Vuelve a intentarlo en {minutos_restantes} minuto(s)."
        )

    if not verify_pin(payload.pin, user.pin_hash):
        user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
        if user.intentos_fallidos >= MAX_PIN_ATTEMPTS:
            user.bloqueado_hasta = now + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PIN incorrecto. Has alcanzado el límite de {MAX_PIN_ATTEMPTS} intentos fallidos."
            )
        db.commit()
        intentos_restantes = MAX_PIN_ATTEMPTS - user.intentos_fallidos
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"PIN incorrecto. Te quedan {intentos_restantes} intento(s)."
        )

    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.commit()

    role_str = user.rol.value if hasattr(user.rol, "value") else str(user.rol)
    access_token = create_access_token(subject=user.id, role=role_str)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserAuthSummary.model_validate(user)
    )