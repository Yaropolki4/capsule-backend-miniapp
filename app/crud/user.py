from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user = User(telegram_id=telegram_id, username=username, first_name=first_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def add_user_photo(db: AsyncSession, user: User, url: str) -> User:
    user.photos = [*(user.photos or []), url]
    flag_modified(user, "photos")
    await db.commit()
    await db.refresh(user)
    return user


async def use_generation(db: AsyncSession, user_id: int) -> bool:
    user = await db.get(User, user_id)
    if not user or user.generations_left <= 0:
        return False
    user.generations_left -= 1
    await db.commit()
    return True


async def set_user_gender(db: AsyncSession, user: User, gender: str) -> User:
    user.gender = gender
    await db.commit()
    await db.refresh(user)
    return user


async def set_waiting_for_photo(db: AsyncSession, user: User, value: bool) -> User:
    user.waiting_for_photo = value
    await db.commit()
    await db.refresh(user)
    return user


async def add_generations(db: AsyncSession, telegram_id: int, amount: int) -> User | None:
    user = await get_user_by_telegram_id(db, telegram_id)
    if not user:
        return None
    user.generations_left += amount
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_user(
    db: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> tuple[User, bool]:
    user = await get_user_by_telegram_id(db, telegram_id)
    if user:
        return user, False
    user = await create_user(db, telegram_id, username, first_name)
    return user, True
