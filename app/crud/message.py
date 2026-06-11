import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


async def get_recent_messages(db: AsyncSession, user_id: int, limit: int = 5) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.user_id == user_id, Message.is_deleted == False)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def update_message_content(db: AsyncSession, message_id: int, content: str) -> None:
    await db.execute(
        update(Message).where(Message.id == message_id).values(content=content)
    )
    await db.commit()


async def update_message(
    db: AsyncSession,
    message_id: int,
    content: str,
    content_type: str,
) -> None:
    await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(content=content, content_type=content_type)
    )
    await db.commit()


async def get_messages(db: AsyncSession, user_id: int) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.user_id == user_id, Message.is_deleted == False)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def create_message(
    db: AsyncSession,
    user_id: int,
    type: str,
    content: str,
    content_type: str = "text",
) -> Message:
    message = Message(user_id=user_id, type=type, content=content, content_type=content_type)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def clear_messages(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(Message)
        .where(Message.user_id == user_id, Message.is_deleted == False)
        .values(is_deleted=True)
    )
    await db.commit()


async def get_shown_item_ids(db: AsyncSession, user_id: int) -> set[int]:
    result = await db.execute(
        select(Message.content).where(
            Message.user_id == user_id,
            Message.is_deleted == False,
            Message.content_type == "recommendation",
        )
    )
    item_ids: set[int] = set()
    for (content,) in result:
        try:
            item_id = json.loads(content).get("item", {}).get("id")
            if isinstance(item_id, int):
                item_ids.add(item_id)
        except Exception:
            pass
    return item_ids
