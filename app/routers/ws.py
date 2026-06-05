import json
import re
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.crud.message import create_message, get_recent_messages, update_message, update_message_content
from app.crud.user import get_user_by_telegram_id
from app.database import AsyncSessionFactory
from app.dependencies import verify_telegram_init_data
from app.schemas.message import IncomingMessage
from app.services.ai import stream_ai_response
from app.services.stylist_prompt import build_system_prompt

router = APIRouter()

_CLOTHES_PATH = Path(__file__).parent.parent.parent / "clothes.json"
_ITEM_MARKER_RE = re.compile(r'\s*\[ITEM:(\d+)\]\s*$')


def _load_item(item_id: int) -> dict | None:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    return next((c for c in clothes if c["id"] == item_id), None)


def _build_history(recent: list) -> list[dict]:
    messages = []
    for m in recent:
        role = "user" if m.type == "user" else "assistant"
        if m.content_type == "recommendation":
            try:
                content = json.loads(m.content).get("text", "")
            except Exception:
                content = m.content
        else:
            content = m.content
        messages.append({"role": role, "content": content})
    return messages


@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket, init_data: str):
    try:
        parsed = verify_telegram_init_data(init_data)
    except Exception:
        await websocket.close(code=4001)
        return

    tg_user = json.loads(parsed.get("user", "{}"))
    telegram_id = tg_user.get("id")
    if not telegram_id:
        await websocket.close(code=4001)
        return

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)

    if not user:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_json()
            event = raw.get("event")

            if event == "user_message":
                async with AsyncSessionFactory() as db:
                    fresh_user = await get_user_by_telegram_id(db, telegram_id)
                if not fresh_user or fresh_user.generations_left <= 0:
                    await websocket.send_json({"event": "no_generations"})
                    continue
                try:
                    msg = IncomingMessage.model_validate(raw)
                except Exception:
                    continue
                async with AsyncSessionFactory() as db:
                    await create_message(
                        db,
                        user_id=user.id,
                        type="user",
                        content=msg.body.payload,
                        content_type=msg.body.type,
                    )
                await _stream_ai(websocket, user.id, gender=fresh_user.gender)

            elif event == "cancel_recommendation":
                await _stream_ai(
                    websocket,
                    user.id,
                    gender=user.gender,
                    synthetic_user_msg="Эта вещь не подошла, предложи другой вариант",
                )

    except WebSocketDisconnect:
        pass


async def _stream_ai(
    websocket: WebSocket,
    user_id: int,
    gender: str | None = None,
    synthetic_user_msg: str | None = None,
) -> None:
    async with AsyncSessionFactory() as db:
        recent = await get_recent_messages(db, user_id, limit=5)

    history = (
        [{"role": "system", "content": build_system_prompt(gender=gender)}]
        + _build_history(recent)
    )
    if synthetic_user_msg:
        history.append({"role": "user", "content": synthetic_user_msg})

    async with AsyncSessionFactory() as db:
        ai_msg = await create_message(
            db,
            user_id=user_id,
            type="ai",
            content="",
            content_type="chunked_text",
        )

    full_content = ""
    try:
        async for chunk in stream_ai_response(history, settings.open_router_key):
            full_content += chunk
            await websocket.send_json({
                "event": "ai_response",
                "body": {
                    "type": "chunked_text",
                    "payload": chunk,
                    "message_id": ai_msg.id,
                },
            })
    except Exception as e:
        print(f"AI streaming error: {e}")
        await websocket.send_json({
            "event": "ai_error",
            "body": {"message_id": ai_msg.id},
        })
        return

    match = _ITEM_MARKER_RE.search(full_content)
    if match:
        item_id = int(match.group(1))
        clean_text = _ITEM_MARKER_RE.sub("", full_content).rstrip()
        item = _load_item(item_id)

        if item:
            item_data = {
                "id": item["id"],
                "title": item["title"],
                "image": item.get("image", ""),
                "link": item["link"],
            }

            await websocket.send_json({
                "event": "ai_message_update",
                "body": {"message_id": ai_msg.id, "content": clean_text},
            })
            await websocket.send_json({
                "event": "ai_recommendation",
                "body": {"message_id": ai_msg.id, "item": item_data},
            })

            async with AsyncSessionFactory() as db:
                await update_message(
                    db,
                    ai_msg.id,
                    content=json.dumps({"text": clean_text, "item": item_data}, ensure_ascii=False),
                    content_type="recommendation",
                )
            return

    if full_content:
        async with AsyncSessionFactory() as db:
            await update_message_content(db, ai_msg.id, full_content)
