from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class UserAvatar(Base):
    __tablename__ = "avatars_usuarios"

    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    imagen: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    usuario: Mapped["User"] = relationship("User", back_populates="avatar")
