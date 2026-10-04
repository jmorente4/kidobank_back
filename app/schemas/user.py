from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100, description="Nombre completo del usuario")
    email: EmailStr = Field(..., description="Correo electrónico único de acceso")
    rol: UserRole = Field(default=UserRole.NINO, description="Rol del usuario en la plataforma (PADRE o NINO)")
    tarjeta_qr: Optional[str] = Field(
        None, max_length=255, description="Identificador único del token o tarjeta QR para el niño"
    )
    codigo_pin: Optional[str] = Field(
        None, min_length=4, max_length=6, description="Código PIN de 4 a 6 dígitos para operaciones rápidas"
    )


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=100, description="Contraseña de acceso del usuario")


class UserUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, max_length=100)
    rol: Optional[UserRole] = None
    tarjeta_qr: Optional[str] = Field(None, max_length=255)
    codigo_pin: Optional[str] = Field(None, min_length=4, max_length=6)


class UserResponse(UserBase):
    id: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)