from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.outfit import Outfit


async def create_outfit(
    db: AsyncSession,
    user_id: int,
    generated_image_url: str,
    item_id: int | None = None,
    item_title: str | None = None,
    item_image_url: str | None = None,
    item_link: str | None = None,
) -> Outfit:
    outfit = Outfit(
        user_id=user_id,
        item_id=item_id,
        item_title=item_title,
        item_image_url=item_image_url,
        item_link=item_link,
        generated_image_url=generated_image_url,
    )
    db.add(outfit)
    await db.commit()
    await db.refresh(outfit)
    return outfit


async def get_user_outfits(db: AsyncSession, user_id: int) -> list[Outfit]:
    result = await db.execute(
        select(Outfit).where(Outfit.user_id == user_id).order_by(Outfit.created_at.desc())
    )
    return list(result.scalars().all())
