"""The way out of this chat into the full product.

The bot keeps its own chat history in its own database and can do less than the site, so every
reply has to offer the site — otherwise a user who started here never learns there is more. The
button is attached centrally by `SiteCtaMiddleware`, not in each handler, so that a reply added
later cannot ship without it.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings

BUTTON_TEXT = "✨ Продолжить на сайте Capsule"


def site_button() -> InlineKeyboardButton | None:
    """`None` when no site is configured — the bot then behaves exactly as it did before."""
    if not settings.site_url:
        return None

    return InlineKeyboardButton(text=BUTTON_TEXT, url=settings.site_url)


def site_cta_keyboard() -> InlineKeyboardMarkup | None:
    """A keyboard holding nothing but the site button."""
    button = site_button()

    return InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None


def with_site_button(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Appends the site row to an inline keyboard, leaving the buttons it already has untouched."""
    button = site_button()
    if button is None:
        return markup

    if markup is None:
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    rows = list(markup.inline_keyboard)

    # A handler may already have built the row itself; two identical buttons would be noise.
    if any(existing.url == button.url for row in rows for existing in row):
        return markup

    return InlineKeyboardMarkup(inline_keyboard=[*rows, [button]])
