from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class IncomingMessageBody(BaseModel):
    type: Literal["text"]
    payload: str


class IncomingMessage(BaseModel):
    event: Literal["user_message"]
    body: IncomingMessageBody


class MessageOut(BaseModel):
    id: int
    user_id: int
    type: str
    content_type: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
