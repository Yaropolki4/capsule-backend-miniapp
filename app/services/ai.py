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
