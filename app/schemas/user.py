from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100, description="Nombre completo del usuario")
    apellidos: Optional[str] = Field(None, max_length=150, description="Apellidos opcionales del usuario")
    avatar_url: Optional[str] = Field(None, max_length=255, description="URL opcional de la imagen de perfil")
    email: EmailStr = Field(..., description="Correo electrónico único de acceso")
    rol: UserRole = Field(default=UserRole.NINO, description="Rol del usuario en la plataforma (PADRE o NINO)")
    tarjeta_qr: Optional[str] = Field(
        None, max_length=255, description="Identificador único del token o tarjeta QR para el niño"
    )
    codigo_pin: Optional[str] = Field(
        None, pattern=r"^\d{4}$", description="Código PIN de cuatro dígitos para acceso infantil"
    )


class UserCreate(UserBase):
    password: Optional[str] = Field(None, min_length=6, max_length=100, description="Contraseña para cuentas de adulto")


class UserUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    apellidos: Optional[str] = Field(None, max_length=150)
    avatar_url: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, max_length=100)
    rol: Optional[UserRole] = None
    tarjeta_qr: Optional[str] = Field(None, max_length=255)
    codigo_pin: Optional[str] = Field(None, pattern=r"^\d{4}$")


class UserProfileUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    apellidos: Optional[str] = Field(None, max_length=150, description="Enviar null para borrar los apellidos")
    avatar_url: Optional[str] = Field(None, max_length=255, description="Enviar null para borrar la imagen de perfil")
    email: Optional[EmailStr] = None


class PinChange(BaseModel):
    pin_nuevo: str = Field(..., pattern=r"^\d{4}$", description="Nuevo PIN de cuatro dígitos")
    pin_actual: Optional[str] = Field(
        None, pattern=r"^\d{4}$", description="PIN actual; obligatorio si lo cambia el propio niño"
    )


class UserResponse(UserBase):
    id: int
    padre_id: Optional[int] = None
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)