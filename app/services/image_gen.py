import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_TRY_ON_PROMPT_BASE = (
    "Virtually dress the person from the first photo in the clothing item from the second photo. "
    "Rules:\n"
    "- Preserve the person's face, skin tone, pose, and body proportions exactly as in the original photo.\n"
    "- Do NOT rotate, flip, mirror, or change the camera angle of the photo in any way.\n"
    "- Preserve the original background and lighting conditions exactly.\n"
    "- Do NOT modify any clothing items not being replaced (e.g. pants, shoes stay the same).\n"
    "- Show realistic fabric draping, wrinkles, and fit as the garment would naturally look on this body.\n"
    "- Do NOT add accessories, jewelry, or other items not present in the original photo.\n"
    "- Output a realistic, high-quality photo at the same resolution and perspective as the input."
)

_ACCESSORY_PROMPT_BASE = (
    "Show the person from the first photo naturally carrying or wearing the bag from the second photo. "
    "Rules:\n"
    "- The bag should appear held in hand, on the shoulder, or crossbody — whichever matches its style.\n"
    "- Preserve the person's face, skin tone, pose, and body proportions exactly as in the original photo.\n"
    "- Do NOT rotate, flip, mirror, or change the camera angle of the photo in any way.\n"
    "- Preserve the original background and lighting conditions exactly.\n"
    "- Do NOT modify any clothing items in the photo.\n"
    "- Show the bag at a realistic size and position, with natural lighting and shadows.\n"
    "- Output a realistic, high-quality photo at the same resolution and perspective as the input."
)


async def _url_to_data_uri(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    data = base64.b64encode(resp.content).decode()
    return f"data:{content_type};base64,{data}"


async def generate_try_on(
    user_photo_url: str, item_image_url: str, api_key: str, generation_prompt: str | None = None, item_type: str | None = None
) -> bytes | None:
    prompt = _ACCESSORY_PROMPT_BASE if item_type == "accessory" else _TRY_ON_PROMPT_BASE
    if generation_prompt:
        prompt += f"\n\nCRITICAL fit requirement — you MUST follow this exactly: {generation_prompt}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        item_data_uri = await _url_to_data_uri(client, item_image_url)

        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.image_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": user_photo_url}},
                            {"type": "image_url", "image_url": {"url": item_data_uri}},
                        ],
                    }
                ],
                "image_config": {"aspect_ratio": "2:3"},
            },
        )
        if not response.is_success:
            logger.error("OpenRouter error %s: %s", response.status_code, response.text)
        response.raise_for_status()
        result = response.json()
        logger.debug("OpenRouter response: %s", result)

    if "error" in result:
        logger.error("OpenRouter error response: %s", result["error"])
        return None

    if not result.get("choices"):
        logger.error("OpenRouter returned no choices: %s", result)
        return None

    message = result["choices"][0]["message"]

    # Gemini-style: images field
    for image in message.get("images", []):
        url = image.get("image_url", {}).get("url", "")
        if url.startswith("data:image"):
            _, data = url.split(",", 1)
            return base64.b64decode(data)
        if url.startswith("http"):
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                return resp.content

    # Grok / standard: content as string URL or content blocks
    content = message.get("content", "")
    if isinstance(content, str):
        if content.startswith("data:image"):
            _, data = content.split(",", 1)
            return base64.b64decode(data)
        if content.startswith("http"):
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(content)
                return resp.content
    elif isinstance(content, list):
        for block in content:
            url = block.get("image_url", {}).get("url", "") if isinstance(block, dict) else ""
            if url.startswith("data:image"):
                _, data = url.split(",", 1)
                return base64.b64decode(data)
            if url.startswith("http"):
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url)
                    return resp.content

    logger.error("Could not extract image from OpenRouter response. message keys=%s content_type=%s", list(message.keys()), type(message.get("content")).__name__)
    return None
