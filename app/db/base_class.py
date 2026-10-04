from typing import Any
from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """
    Clase base declarativa para SQLAlchemy v2.
    Genera automáticamente el nombre de la tabla a partir del nombre de la clase en minúsculas
    si no se especifica explícitamente __tablename__.
    """
    id: Any
    __name__: str

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()