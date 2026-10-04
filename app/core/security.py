from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Configuración del contexto de encriptación con bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _truncate_password(password: str) -> str:
    """
    Bcrypt limita las contraseñas a 72 bytes.
    Truncamos la cadena a 72 bytes codificados en UTF-8 para evitar ValueError.
    """
    if not password:
        return ""
    # Trunca estrictamente a 72 bytes en UTF-8 sin cortar caracteres a la mitad
    password_bytes = password.encode("utf-8")[:72]
    return password_bytes.decode("utf-8", errors="ignore")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña en texto plano contra su hash."""
    safe_password = _truncate_password(plain_password)
    return pwd_context.verify(safe_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Genera el hash bcrypt de una contraseña."""
    safe_password = _truncate_password(password)
    return pwd_context.hash(safe_password)


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """
    Verifica un PIN numérico (4 o 6 dígitos) contra su hash.
    """
    safe_pin = _truncate_password(str(plain_pin))
    return pwd_context.verify(safe_pin, hashed_pin)


def get_pin_hash(pin: str) -> str:
    """Genera el hash bcrypt para un PIN numérico."""
    safe_pin = _truncate_password(str(pin))
    return pwd_context.hash(safe_pin)


def create_access_token(
    subject: Union[str, int, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Crea un token JWT firmado con el ID del usuario en la clave 'sub'.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 8)
        )

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.now(timezone.utc),
    }

    secret_key = getattr(settings, "SECRET_KEY", "SECRET_KEY_SUPER_SECRETA_KIDOBANK")
    algorithm = getattr(settings, "ALGORITHM", "HS256")

    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodifica y valida un token JWT. Devuelve el payload si es válido o None si expiró/es inválido.
    """
    secret_key = getattr(settings, "SECRET_KEY", "SECRET_KEY_SUPER_SECRETA_KIDOBANK")
    algorithm = getattr(settings, "ALGORITHM", "HS256")

    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return payload
    except jwt.PyJWTError:
        return None