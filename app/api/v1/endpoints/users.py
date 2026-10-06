import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    can_access_user,
    family_key,
    get_current_parent,
    get_current_user,
    get_db,
    get_family_user_ids,
    get_optional_current_user,
)
from app.core.security import get_password_hash, verify_pin
from app.models.account import Account, AccountType
from app.models.bond import Bond
from app.models.qr_card import QrCard
from app.models.user import ADMIN_ROLES, MEMBER_ROLES, User, UserRole
from app.schemas.qr_card import QrCardCreate, QrCardResponse, QrCardUpdate
from app.schemas.user import PinChange, UserCreate, UserProfileUpdate, UserResponse
from app.models.user_avatar import UserAvatar
from app.services.avatar import MAX_UPLOAD_BYTES, optimize_avatar
from app.services.login_attempts import MAX_FAILED_ATTEMPTS, check_lockout, lock_auth_user, record_failed_attempt

router = APIRouter()
logger = logging.getLogger(__name__)


def _create_user(
    payload: UserCreate, db: Session, parent: Optional[User] = None
) -> User:
    existing_user = db.scalars(select(User).where(User.email == payload.email)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este correo electrónico",
        )

    password_or_pin = payload.codigo_pin if payload.rol in MEMBER_ROLES else payload.password
    if not password_or_pin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="NINO/FAMILIAR requieren PIN; PADRE/MADRE requieren contraseña.",
        )

    new_user = User(
        nombre=payload.nombre,
        apellidos=payload.apellidos,
        avatar_url=payload.avatar_url,
        email=payload.email,
        pin_hash=get_password_hash(password_or_pin),
        rol=payload.rol,
        padre_id=parent.id if parent and payload.rol in MEMBER_ROLES else None,
        familia_id=family_key(parent) if parent else None,
        qr_uuid=payload.tarjeta_qr if payload.rol in MEMBER_ROLES else None,
    )
    try:
        db.add(new_user)
        db.flush()
        if parent is None:
            new_user.familia_id = new_user.id
        if payload.tarjeta_qr and payload.rol in MEMBER_ROLES:
            db.add(QrCard(qr_uuid=payload.tarjeta_qr, usuario_id=new_user.id))
        db.add(
            Account(
                usuario_id=new_user.id,
                nombre="Cuenta corriente",
                tipo=AccountType.CORRIENTE,
                saldo=0.0,
                tasa_interes=0.0,
            )
        )
        db.commit()
        db.refresh(new_user)
        return new_user
    except IntegrityError as exc:
        db.rollback()
        logger.info("Conflicto de unicidad al registrar un usuario: %s", exc.orig)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo o la tarjeta QR ya están registrados.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Error al guardar el usuario")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al guardar el usuario en la base de datos",
        ) from exc


@router.get(
    "/",
    response_model=List[UserResponse],
    summary="Listar usuarios de la familia",
)
def list_users(
    rol: Optional[UserRole] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(User).where(User.id.in_(get_family_user_ids(current_user, db)))
    if rol:
        stmt = stmt.where(User.rol == rol)
    stmt = stmt.order_by(User.id.asc()).offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.get("/me", response_model=UserResponse, summary="Obtener perfil del usuario autenticado")
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/children", response_model=List[UserResponse], summary="Listar los hijos del padre autenticado")
def list_children(
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(User)
        .where(User.id.in_(get_family_user_ids(current_parent, db)), User.rol == UserRole.NINO)
        .order_by(User.id.asc())
    ).all()


@router.post(
    "/children",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un hijo vinculado al padre autenticado",
)
def create_child(
    payload: UserCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    if payload.rol != UserRole.NINO or not payload.codigo_pin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El alta de un hijo requiere rol NINO y un PIN de cuatro dígitos.",
        )
    return _create_user(payload, db, parent=current_parent)


@router.get("/{user_id}", response_model=UserResponse, summary="Obtener usuario de la familia por ID")
def get_user_by_id(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario especificado no existe")
    if not can_access_user(current_user, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este usuario")
    return user


def _get_accessible_user(user_id: int, current_user: User, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario especificado no existe")
    if not can_access_user(current_user, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este usuario")
    return user


@router.post(
    "/{user_id}/avatar",
    response_model=UserResponse,
    summary="Subir una foto de perfil desde la cámara o un archivo",
    description=(
        "Enviar multipart/form-data con el campo file. Acepta JPEG, PNG y WebP "
        "hasta 5 MB y 20 megapíxeles. Guarda un JPEG de hasta 512 x 512 sin metadatos. "
        "avatar_url es una ruta relativa al backend; para consultarla se requiere Bearer."
    ),
)
def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_accessible_user(user_id, current_user, db)
    image = optimize_avatar(file.file.read(MAX_UPLOAD_BYTES + 1))
    if user.avatar is None:
        user.avatar = UserAvatar(imagen=image)
    else:
        user.avatar.imagen = image
    user.avatar_url = f"/api/v1/users/{user.id}/avatar"
    db.commit()
    db.refresh(user)
    return user


@router.get(
    "/{user_id}/avatar",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
    summary="Consultar la foto de perfil almacenada",
    description="Requiere Bearer. Descargar como Blob para mostrarla en el frontend.",
)
def get_avatar(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_accessible_user(user_id, current_user, db)
    if user.avatar is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay foto de perfil almacenada")
    return Response(
        content=user.avatar.imagen,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.patch("/{user_id}", response_model=UserResponse, summary="Modificar el perfil de un usuario de la familia")
def update_user(
    user_id: int,
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_accessible_user(user_id, current_user, db)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field in ("apellidos", "avatar_url"):
        if field in payload.model_fields_set:
            data[field] = getattr(payload, field)

    if "email" in data and data["email"] != user.email:
        if db.scalars(select(User.id).where(User.email == data["email"])).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe un usuario registrado con este correo electrónico",
            )
    if "avatar_url" in data and data["avatar_url"] != user.avatar_url:
        user.avatar = None
    for field, value in data.items():
        setattr(user, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este correo electrónico",
        ) from exc
    db.refresh(user)
    return user


@router.patch(
    "/{user_id}/pin",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cambiar el PIN de NINO/FAMILIAR",
    description="3 fallos bloquean hasta el desbloqueo por PADRE/MADRE de la familia. Cambiar el PIN no desbloquea.",
)
def change_pin(
    user_id: int,
    payload: PinChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    child = _get_accessible_user(user_id, current_user, db)
    if child.rol not in MEMBER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo los usuarios NINO o FAMILIAR tienen PIN.",
        )
    if current_user.id == child.id:
        if not payload.pin_actual:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El PIN actual no es correcto")
        child = lock_auth_user(db, child.id)
        now = datetime.now(timezone.utc)
        check_lockout(child, now)
        if not verify_pin(payload.pin_actual, child.pin_hash):
            record_failed_attempt(db, child, now)
            check_lockout(child, now)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El PIN actual no es correcto")
    else:
        child = lock_auth_user(db, child.id)

    child.pin_hash = get_password_hash(payload.pin_nuevo)
    if not child.bloqueado_por_pin and child.intentos_fallidos < MAX_FAILED_ATTEMPTS:
        child.intentos_fallidos = 0
        child.bloqueado_hasta = None
    db.commit()


@router.post(
    "/{user_id}/unlock",
    response_model=UserResponse,
    summary="Desbloquear el acceso por PIN de NINO/FAMILIAR",
    description="Solo PADRE/MADRE de su familia. Reinicia los intentos sin cambiar el PIN.",
)
def unlock_child(
    user_id: int,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = lock_auth_user(db, _get_managed_child(user_id, current_parent, db).id)
    child.bloqueado_por_pin = False
    child.intentos_fallidos = 0
    child.bloqueado_hasta = None
    db.commit()
    db.refresh(child)
    return child


def _get_managed_child(user_id: int, current_parent: User, db: Session) -> User:
    child = _get_accessible_user(user_id, current_parent, db)
    if child.rol not in MEMBER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden gestionar miembros NINO o FAMILIAR.",
        )
    return child


def _clear_legacy_qr(user: User, qr_uuid: str) -> None:
    # El login por QR también consulta este campo sin comprobar si la tarjeta está activa.
    if user.qr_uuid == qr_uuid:
        user.qr_uuid = None


@router.get(
    "/{user_id}/cards",
    response_model=List[QrCardResponse],
    summary="Listar las tarjetas QR de un usuario de la familia",
)
def list_user_cards(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_accessible_user(user_id, current_user, db)
    return db.scalars(
        select(QrCard).where(QrCard.usuario_id == user.id).order_by(QrCard.id.desc())
    ).all()


@router.post(
    "/{user_id}/cards",
    response_model=QrCardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Emitir una tarjeta QR para NINO/FAMILIAR (revoca las anteriores)",
)
def issue_user_card(
    user_id: int,
    payload: QrCardCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = _get_managed_child(user_id, current_parent, db)

    if payload.qr_uuid:
        taken = db.scalars(
            select(User.id).where(User.qr_uuid == payload.qr_uuid)
        ).first() or db.scalars(select(QrCard.id).where(QrCard.qr_uuid == payload.qr_uuid)).first()
        if taken:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Esa tarjeta QR ya está registrada.",
            )

    try:
        for card in db.scalars(
            select(QrCard).where(QrCard.usuario_id == child.id, QrCard.activa.is_(True))
        ).all():
            card.activa = False
            _clear_legacy_qr(child, card.qr_uuid)

        new_card = QrCard(usuario_id=child.id, activa=True)
        if payload.qr_uuid:
            new_card.qr_uuid = payload.qr_uuid
        db.add(new_card)
        db.commit()
        db.refresh(new_card)
        return new_card
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esa tarjeta QR ya está registrada.",
        ) from exc


@router.patch(
    "/{user_id}/cards/{card_id}",
    response_model=QrCardResponse,
    summary="Activar o revocar una tarjeta QR de NINO/FAMILIAR",
)
def update_user_card(
    user_id: int,
    card_id: int,
    payload: QrCardUpdate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = _get_managed_child(user_id, current_parent, db)
    card = db.get(QrCard, card_id)
    if card is None or card.usuario_id != child.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La tarjeta no existe")

    card.activa = payload.activa
    if not payload.activa:
        _clear_legacy_qr(child, card.qr_uuid)
    db.commit()
    db.refresh(card)
    return card


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un miembro NINO/FAMILIAR y todos sus datos",
)
def delete_child(
    user_id: int,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = _get_managed_child(user_id, current_parent, db)
    saldo_total = db.scalar(select(func.coalesce(func.sum(Account.saldo), 0.0)).where(Account.usuario_id == child.id))
    if saldo_total > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede eliminar: el hijo aún tiene {saldo_total:.2f} Kidos en sus cuentas.",
        )
    try:
        db.execute(delete(Bond).where(Bond.usuario_id == child.id))
        db.delete(child)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Error al eliminar al hijo %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo eliminar al usuario",
        ) from exc


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un adulto o crear un usuario de la familia",
)
def create_user(
    payload: UserCreate,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        if payload.rol not in ADMIN_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El registro público solo permite PADRE/MADRE; los miembros requieren un administrador.",
            )
        return _create_user(payload, db)

    if current_user.rol not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo PADRE/MADRE pueden crear usuarios vinculados a su familia.",
        )
    if payload.rol in MEMBER_ROLES and not payload.codigo_pin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="NINO/FAMILIAR requieren un PIN de cuatro dígitos.",
        )
    return _create_user(payload, db, parent=current_user)
