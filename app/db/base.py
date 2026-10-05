# Módulo de registro centralizado para SQLAlchemy y Alembic
from app.db.base_class import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.qr_card import QrCard  # noqa: F401
from app.models.account import Account  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.goal import Goal  # noqa: F401
from app.models.economy import InflationPolicy  # noqa: F401
from app.models.investment import InvestmentProduct, UserInvestment, MarketNews  # noqa: F401
from app.models.market import MarketItem, EscrowTransaction  # noqa: F401