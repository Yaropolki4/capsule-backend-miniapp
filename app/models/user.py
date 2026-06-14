from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generations_left: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    photos: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    waiting_for_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pending_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_started_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
