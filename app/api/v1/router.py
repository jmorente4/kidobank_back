from fastapi import APIRouter

# Asumiendo una estructura típica donde cada módulo exporta su 'router'
# (p. ej., app/api/v1/endpoints/auth.py o app/api/v1/auth.py)
from app.api.v1.endpoints import accounts, auth, transactions, users

api_router = APIRouter()

# Autenticación y tokens
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)

# Gestión de usuarios
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users"]
)

# Cuentas bancarias o de trading
api_router.include_router(
    accounts.router,
    prefix="/accounts",
    tags=["Accounts"]
)

# Transacciones e historial
api_router.include_router(
    transactions.router,
    prefix="/transactions",
    tags=["Transactions"]
)