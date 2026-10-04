from datetime import datetime, timezone
from typing import Callable, Generator, List, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User, UserRole

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    """
    Proporciona una sesión aislada de SQLAlchemy por petición y la cierra al finalizar.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Extrae y valida el JWT del header Bearer, recupera el objeto User desde la BD
    y verifica que la cuenta no esté bloqueada por intentos de PIN fallidos.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales o el token ha expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise credentials_exception

    try:
        user_id = int(user_id_raw)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    # Control de bloqueo temporal por seguridad
    if user.bloqueado_hasta and user.bloqueado_hasta > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta se encuentra bloqueada temporalmente por seguridad."
        )

    return user


def require_role(allowed_roles: Union[UserRole, List[UserRole]]) -> Callable:
    """
    Factoría de dependencias para restringir endpoints según el rol del usuario.
    """
    if isinstance(allowed_roles, UserRole):
        roles_list = [allowed_roles]
    else:
        roles_list = allowed_roles

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.rol not in roles_list:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: No dispones de los permisos necesarios."
            )
        return current_user

    return role_checker


def get_current_parent(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependencia rápida para asegurar que el usuario es exclusivamente un PADRE.
    """
    if current_user.rol != UserRole.PADRE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Se requieren permisos de Padre."
        )
    return current_user


def get_current_child(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependencia rápida para asegurar que el usuario es un NIÑO.
    """
    if current_user.rol != UserRole.NINO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Se requieren permisos de Niño."
        )
    return current_user