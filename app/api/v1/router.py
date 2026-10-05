from fastapi import APIRouter

from app.api.v1.endpoints import accounts, auth, bonds, market, transactions, users

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

# Renta Fija (Bonos)
api_router.include_router(
    bonds.router,
    prefix="/bonds",
    tags=["Renta Fija (Bonos)"]
)

# Mercadillo familiar con escrow
api_router.include_router(
    market.router,
    prefix="/market",
    tags=["Mercadillo"]
)