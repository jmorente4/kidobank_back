from datetime import datetime, timezone
from typing import Callable, Generator, List, Optional, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.services.login_attempts import check_lockout

security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """
    Proporciona una sesión aislada de SQLAlchemy por petición y la cierra al finalizar.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Extrae y valida el JWT del header Bearer, recupera el objeto User desde la BD
    y verifica que la cuenta no esté bloqueada por intentos de PIN fallidos.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales o el token ha expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise credentials_exception

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    check_lockout(user, datetime.now(timezone.utc))

    return user


def get_current_user(
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_family_user_ids(current_user: User, db: Session) -> List[int]:
    """IDs visible to a user: their own account and linked family members."""
    if current_user.rol == UserRole.PADRE:
        children = db.scalars(select(User.id).where(User.padre_id == current_user.id)).all()
        return [current_user.id, *children]
    return [current_user.id]


def can_access_user(current_user: User, target_user: User) -> bool:
    if current_user.id == target_user.id:
        return True
    if current_user.rol == UserRole.PADRE:
        return target_user.padre_id == current_user.id
    return False


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