from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.models.user import UserRole
from app.schemas.username import Username


class LoginRequest(BaseModel):
    username: str = Field(..., description="Email del padre o nombre/alias del niño")
    password: str = Field(..., description="Contraseña del padre o clave del niño")


class ParentLoginRequest(BaseModel):
    email: str = Field(..., description="Email del padre")
    password: str = Field(..., description="Contraseña del padre")


class PinLoginRequest(BaseModel):
    pin: str = Field(..., pattern=r"^\d{4}$", description="PIN numérico de cuatro dígitos")
    user_id: Optional[int] = Field(None, description="ID del usuario (para selección por avatar)")
    qr_uuid: Optional[str] = Field(None, description="UUID de la tarjeta QR escaneada")
    nombre_usuario: Optional[Username] = Field(
        None, description="Apodo de NINO/FAMILIAR; usar sin user_id ni qr_uuid"
    )


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=32, max_length=200)
    new_password: str = Field(..., min_length=6, max_length=100)


class UserAuthSummary(BaseModel):
    id: int
    familia_id: Optional[int] = None
    nombre: str
    nombre_usuario: Optional[str] = None
    apellidos: Optional[str] = None
    email: Optional[str] = None
    rol: UserRole
    avatar_url: Optional[str] = None
    qr_uuid: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserAuthSummary