"""TypeSafe's Jev decision model, through OpenRouter's Decisions API."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import requests
from django.conf import settings

API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
# Connect and read; a call takes about 200 ms, and a slow one is skipped.
_TIMEOUT_SECONDS = (3, 5)


class DecisionError(Exception):
    """Jev returned no usable answer."""


@dataclass(frozen=True)
class Decision:
    model: str
    # The probability Jev gave "true", by question name.
    answers: dict[str, float]
    cost_microusd: int | None


class JevClient:
    """Asks Jev yes/no (``noul``) questions about a state."""

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
    def from_settings(cls) -> JevClient | None:
        """The client when screening is on and ``OPENROUTER_API_KEY`` is set."""
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or ""
        if not (settings.RESEARCH_AI_MESSAGE_SCREENING and api_key):
            return None
        return cls(api_key)

    def decide(self, state: dict, questions: dict[str, dict]) -> Decision:
        try:
            response = self.session.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "state": state,
                    "questions": questions,
                    "provider": {"zdr": True},
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
            answers = {name: body["answers"][name]["noul"] for name in questions}
        except (requests.RequestException, ValueError, LookupError, TypeError) as exc:
            raise DecisionError(f"Jev returned no decision: {exc}") from exc
        for name, value in answers.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise DecisionError(f"Jev answered {name!r} with {value!r}")
        return Decision(
            model=body.get("model") or self.model,
            answers={name: float(value) for name, value in answers.items()},
            cost_microusd=_microusd((body.get("usage") or {}).get("cost")),
        )


def _microusd(cost) -> int | None:
    try:
        value = Decimal(str(cost)) * 1_000_000
    except InvalidOperation, ValueError:
        return None
    if not value.is_finite() or value < 0:
        return None
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
