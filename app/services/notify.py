import logging
import traceback

import httpx

logger = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org"


async def notify_admin(text: str, bot_token: str, admin_chat_id: str) -> None:
    """Fire-and-forget Telegram alert to admin. Silently swallows send failures."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{_TG_API}/bot{bot_token}/sendMessage",
                json={"chat_id": admin_chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception:
        logger.exception("Failed to send admin Telegram notification")


def format_error_message(method: str, path: str, status: int, detail: str, tb: str | None = None) -> str:
    lines = [
        f"🚨 <b>Server Error</b>",
        f"<b>Request:</b> {method} {path}",
        f"<b>Status:</b> {status}",
        f"<b>Detail:</b> {detail}",
    ]
    if tb:
        truncated = tb[-1500:] if len(tb) > 1500 else tb
        lines.append(f"\n<pre>{truncated}</pre>")
    return "\n".join(lines)
