from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import Response, SendMessage, SendPhoto, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import InlineKeyboardMarkup, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.site_cta import with_site_button


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["db"] = session
            return await handler(event, data)


class SiteCtaMiddleware(BaseRequestMiddleware):
    """Puts the site button under every message the bot sends.

    An outgoing-request middleware rather than an edit in every handler: messages leave from six
    handlers plus the generation pipeline, and this is the single place that also covers the ones
    written later. Admin alerts are unaffected — they go out over raw HTTP, not the bot session.
    """

    # Only message sends carry a keyboard a user is meant to act on; `answerCallbackQuery`,
    # chat actions and the edits in the rating flow are left alone.
    _SUPPORTED_METHODS = (SendMessage, SendPhoto)

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if isinstance(method, self._SUPPORTED_METHODS):
            markup = method.reply_markup

            # A reply keyboard or a force-reply is a different kind of markup: appending an inline
            # row to it is not possible, and replacing it would break the handler that asked for it.
            if markup is None or isinstance(markup, InlineKeyboardMarkup):
                method.reply_markup = with_site_button(markup)

        return await make_request(bot, method)
