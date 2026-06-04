from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Outfit(Base):
    __tablename__ = "outfits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    item_link: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_image_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
