"""Mistral OCR as the engine for PDF pages that have no text layer."""

import base64
import re

import requests
from django.conf import settings

from research_ai.services.agent_files.extraction import PageImage
from research_ai.services.agent_files.ocr import OcrError

API_URL = "https://api.mistral.ai/v1/ocr"
# The alias tracks Mistral's current OCR model; pinned versions retire in months.
MODEL = "mistral-ocr-latest"
# Connect and read; a page that takes longer stays marked as unread.
_TIMEOUT_SECONDS = (5, 20)
# Figures come back as links to crops the request does not ask for.
_FIGURE_PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)\s*")


class MistralOcr:
    """Reads a page image with Mistral OCR, which returns it as Markdown."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.session = requests.Session() if session is None else session

    @classmethod
    def from_settings(cls) -> "MistralOcr | None":
        """The engine when ``MISTRAL_API_KEY`` is set, else ``None``."""
        api_key = getattr(settings, "MISTRAL_API_KEY", "") or ""
        return cls(api_key) if api_key else None

    def read_page(self, image: PageImage) -> str:
        encoded = base64.b64encode(image.data).decode("ascii")
        try:
            response = self.session.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:{image.media_type};base64,{encoded}",
                    },
                    "include_image_base64": False,
                    "include_blocks": False,
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            markdown = response.json()["pages"][0]["markdown"]
        except (requests.RequestException, ValueError, LookupError, TypeError) as exc:
            raise OcrError(f"Mistral OCR could not read page {image.page}") from exc
        if not isinstance(markdown, str):
            raise OcrError(f"Mistral OCR returned no text for page {image.page}")
        text = _FIGURE_PLACEHOLDER.sub("", markdown).strip()
        # A page holding only a figure comes back as stray symbols such as "☐".
        return text if any(map(str.isalnum, text)) else ""
