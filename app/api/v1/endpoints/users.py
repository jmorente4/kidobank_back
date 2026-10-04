from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, get_current_parent
from app.core.security import get_password_hash
from app.models.account import Account, AccountType
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse


router = APIRouter()


@router.get(
    "/",
    response_model=List[UserResponse],
    summary="Listar usuarios de la plataforma",
)
def list_users(
    rol: Optional[UserRole] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Obtiene la lista de usuarios.
    - Los usuarios autenticados pueden consultar el listado y filtrar opcionalmente por rol (`PADRE` o `NINO`).
    """
    stmt = select(User)
    if rol:
        stmt = stmt.where(User.rol == rol)

    stmt = stmt.order_by(User.id.asc()).offset(offset).limit(limit)
    users = db.scalars(stmt).all()
    return users


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Obtener perfil del usuario autenticado",
)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Devuelve los datos del perfil del usuario que realiza la petición.
    """
    return current_user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Obtener usuario por ID",
)
def get_user_by_id(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Obtiene los detalles de un usuario específico por su ID.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario especificado no existe",
        )
    return user


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo usuario (Padre o Niño)",
)
def create_user(
    payload: UserCreate,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Crea un nuevo usuario en Kidobank.
    - **Rol PADRE**: Puede registrarse como autoregistro inicial o ser creado por otro padre.
    - **Rol NIÑO**: Requiere obligatoriamente que la petición sea realizada por un usuario con rol **PADRE**.
    - Al crear un **NIÑO**, se inicializa automáticamente su cuenta bancaria principal con saldo 0 Kidos.
    """
    # Si se crea un NIÑO, exige permiso explicito de PADRE
    if payload.rol == UserRole.NINO:
        if not current_user or current_user.rol != UserRole.PADRE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un usuario con rol PADRE puede crear cuentas de NIÑOS",
            )

    # Verificar que el correo no esté registrado previamente
    stmt_check = select(User).where(User.email == payload.email)
    existing_user = db.scalars(stmt_check).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este correo electrónico",
        )

    try:
        hashed_pwd = get_password_hash(payload.password)

        new_user = User(
            nombre=payload.nombre,
            email=payload.email,
            hashed_password=hashed_pwd,
            rol=payload.rol,
            tarjeta_qr=getattr(payload, "tarjeta_qr", None),
            codigo_pin=getattr(payload, "codigo_pin", None),
        )

        db.add(new_user)
        db.flush()  # Genera el ID de new_user antes del commit

        # Si el usuario creado es un NIÑO, asignarle su cuenta bancaria inicial
        if new_user.rol == UserRole.NINO:
            cuenta_inicial = Account(
                usuario_id=new_user.id,
                tipo=AccountType.CORRIENTE,
                saldo=0.0,
                tasa_interes=0.0,
            )
            db.add(cuenta_inicial)

        db.commit()
        db.refresh(new_user)

        return new_user

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al guardar el usuario en la base de datos",
        )