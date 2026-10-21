"""Text-to-image generation through OpenRouter's Image API (``POST /images``).

https://openrouter.ai/docs/guides/overview/multimodal/image-generation
"""

import base64

import httpx

OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
# Each call; generous because detailed images can take minutes to render.
TIMEOUT_SECONDS = 240


class OpenRouterImageError(RuntimeError):
    """OpenRouter refused the request or returned no image."""


class OpenRouterImageClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.http = http if http is not None else httpx.Client(timeout=TIMEOUT_SECONDS)

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        quality: str | None = None,
    ) -> bytes:
        """The bytes of one image for ``prompt``, in the provider's format."""
        body = {"model": model, "prompt": prompt, "n": 1}
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if quality:
            body["quality"] = quality

        response = self.http.post(
            OPENROUTER_IMAGES_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        )
        if response.is_error:
            raise OpenRouterImageError(
                f"OpenRouter image request failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
        images = response.json().get("data") or []
        if not images or not images[0].get("b64_json"):
            raise OpenRouterImageError("OpenRouter returned no image")
        return base64.b64decode(images[0]["b64_json"])
