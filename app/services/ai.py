import base64
import json
from collections.abc import AsyncGenerator

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-haiku-4-5"


async def infer_gender_from_name(first_name: str, api_key: str) -> str | None:
    messages = [
        {
            "role": "user",
            "content": (
                f'Определи пол человека по имени "{first_name}". '
                'Ответь строго одним словом: "male" или "female". '
                'Если определить невозможно — ответь "unknown".'
            ),
        }
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "stream": False,
                "max_tokens": 5,
            },
        )
        response.raise_for_status()
        data = response.json()
        result = data["choices"][0]["message"]["content"].strip().lower()
        return result if result in ("male", "female") else None


async def select_best_photo(photo_bytes_list: list[bytes], gender: str, api_key: str) -> int | None:
    """Returns 0-based index of the best photo for try-on, or None if no suitable photo found."""
    if gender == "female":
        criteria = (
            "We need a full body photo (whole figure visible) for virtual dress try-on. "
            "If no full body photo exists, a clear upper body photo (chest and up) is acceptable."
        )
    else:
        criteria = (
            "We need a clear upper body photo (chest, shoulders, face visible) for virtual hoodie try-on. "
            "If no upper body photo exists, a full body photo is acceptable."
        )

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Select the best photo for virtual clothing try-on. {criteria} "
                "The photo must show a single real person facing roughly forward with good lighting. "
                "Photos of animals, objects, landscapes, memes, or groups are NOT suitable. "
                f"There are {len(photo_bytes_list)} photo(s) indexed 0 to {len(photo_bytes_list) - 1}. "
                "Respond with ONLY a single integer: the index of the best photo, or -1 if none are suitable."
            ),
        }
    ]
    for photo_bytes in photo_bytes_list:
        b64 = base64.b64encode(photo_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 5},
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()

    try:
        idx = int(raw)
    except ValueError:
        return None

    if idx == -1:
        return None
    if 0 <= idx < len(photo_bytes_list):
        return idx
    return None


async def stream_ai_response(
    messages: list[dict],
    api_key: str,
) -> AsyncGenerator[str, None]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    return
                parsed = json.loads(data)
                delta = parsed["choices"][0]["delta"].get("content") or ""
                if delta:
                    yield delta
