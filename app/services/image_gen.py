import base64

import httpx

from app.config import settings

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


async def generate_try_on(
    user_photo_url: str, item_image_url: str, api_key: str, generation_prompt: str | None = None
) -> bytes | None:
    prompt = _TRY_ON_PROMPT_BASE
    if generation_prompt:
        prompt += f"\n\nCRITICAL fit requirement — you MUST follow this exactly: {generation_prompt}"

    async with httpx.AsyncClient(timeout=120.0) as client:
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
                            {"type": "image_url", "image_url": {"url": item_image_url}},
                        ],
                    }
                ],
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "2:3"},
            },
        )
        response.raise_for_status()
        result = response.json()

    if not result.get("choices"):
        return None

    message = result["choices"][0]["message"]
    for image in message.get("images", []):
        url = image.get("image_url", {}).get("url", "")
        if url.startswith("data:image"):
            _, data = url.split(",", 1)
            return base64.b64decode(data)
        if url.startswith("http"):
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                return resp.content

    return None
