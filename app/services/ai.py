import base64
import json
import logging
from collections.abc import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-haiku-4-5"
OPENROUTER_MODEL_VISION = "google/gemini-2.5-flash"


async def infer_gender_from_name(first_name: str, api_key: str) -> str | None:
    logger.info("infer_gender_from_name name=%r", first_name)
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
        raw = data["choices"][0]["message"]["content"].strip().lower()
        result = raw if raw in ("male", "female") else None
        logger.info("infer_gender_from_name name=%r raw=%r -> %r", first_name, raw, result)
        return result


async def select_best_photo(photo_bytes_list: list[bytes], gender: str, api_key: str) -> int | None:
    """Returns 0-based index of the best photo for try-on, or None if no suitable photo found."""
    n = len(photo_bytes_list)
    logger.info("select_best_photo n=%d gender=%r", n, gender)

    if gender == "female":
        preference = "Prefer a full body shot, but a face or upper body photo is fine too."
    else:
        preference = "Prefer an upper body shot, but a face or full body photo is fine too."

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Pick the best photo of a real person for virtual clothing try-on. {preference} "
                "Any photo that clearly shows a real human is suitable — face shots are OK. "
                "Only return -1 if a photo contains NO real person at all (animal, object, meme, landscape). "
                f"There are {n} photo(s) indexed 0 to {n - 1}. "
                "Respond with ONLY a single integer: the index of the best photo, or -1 if none contain a real person."
            ),
        }
    ]
    total_b64_bytes = 0
    for photo_bytes in photo_bytes_list:
        b64 = base64.b64encode(photo_bytes).decode()
        total_b64_bytes += len(b64)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    logger.info("select_best_photo total_b64_size=%d bytes", total_b64_bytes)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": OPENROUTER_MODEL_VISION, "messages": [{"role": "user", "content": content}], "max_tokens": 5},
        )
        if not response.is_success:
            logger.error("select_best_photo LLM error status=%d body=%r", response.status_code, response.text[:300])
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()

    logger.info("select_best_photo LLM raw response=%r", raw)

    try:
        idx = int(raw)
    except ValueError:
        logger.warning("select_best_photo could not parse %r as int -> returning None", raw)
        return None

    if idx == -1:
        logger.info("select_best_photo LLM returned -1 (no real person detected)")
        return None
    if 0 <= idx < n:
        logger.info("select_best_photo -> index %d", idx)
        return idx

    logger.warning("select_best_photo idx=%d out of range n=%d -> returning None", idx, n)
    return None


async def complete_ai_response(messages: list[dict], api_key: str) -> str:
    full = ""
    async for chunk in stream_ai_response(messages, api_key):
        full += chunk
    return full


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
