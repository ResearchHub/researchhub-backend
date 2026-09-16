"""Eval-only TypeSafe System One client (Jev).

Not wired into the agent loop, payments, or any production path. Callers inject
``http_post`` in tests so CI never hits ``api.typesafe.ai``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

HttpPost = Callable[..., Any]


class TypeSafeError(RuntimeError):
    """TypeSafe client failure. Messages must never include the API key."""


@dataclass(frozen=True)
class TypeSafeEvaluation:
    """Parsed System One response plus client-side latency."""

    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, Any]
    latency_ms: float


class TypeSafeClient:
    """POST ``/v1/systemone`` with constructor-injected transport and key."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_post: HttpPost | None = None,
        timeout: float = 30.0,
        model: str = DEFAULT_MODEL,
        endpoint: str = SYSTEMONE_URL,
    ):
        if api_key is None:
            api_key = getattr(settings, "TYPESAFE_API_KEY", "") or ""
        self._api_key = api_key
        self._http_post = http_post or requests.post
        self._timeout = timeout
        self._model = model
        self._endpoint = endpoint

    def evaluate(
        self,
        state: Any,
        questions: dict[str, dict[str, Any]],
    ) -> TypeSafeEvaluation:
        """Evaluate ``questions`` against ``state``; never logs the API key."""
        if not self._api_key:
            raise TypeSafeError("TYPESAFE_API_KEY is not configured")
        payload = {
            "state": state,
            "model": self._model,
            "questions": questions,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            response = self._http_post(
                self._endpoint,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TypeSafeError(
                f"TypeSafe request failed ({type(exc).__name__})"
            ) from None
        latency_ms = (time.perf_counter() - started) * 1000
        status = getattr(response, "status_code", None)
        body_text = self._redact(getattr(response, "text", "") or "")
        if status != 200:
            raise TypeSafeError(
                f"TypeSafe request returned HTTP {status}: {body_text[:500]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TypeSafeError("TypeSafe response was not JSON") from exc
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeError("TypeSafe response missing answers object")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        model = body.get("model") or self._model
        logger.info(
            "TypeSafe evaluate completed status=%s latency_ms=%.0f questions=%d",
            status,
            latency_ms,
            len(questions),
        )
        return TypeSafeEvaluation(
            model=str(model),
            answers=answers,
            usage=usage,
            latency_ms=latency_ms,
        )

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[redacted]")
        return text
