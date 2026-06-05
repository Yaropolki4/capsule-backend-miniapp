from datetime import datetime

from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    generations_left: int
    created_at: datetime
    gender: str | None

    model_config = {"from_attributes": True}
