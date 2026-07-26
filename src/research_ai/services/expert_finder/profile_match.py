import json
import logging
import re
from typing import Any

from research_ai.models import Expert
from research_ai.prompts.expert_finder_prompts import (
    PROFILE_MATCH_SYSTEM_PROMPT,
    build_profile_match_user_prompt,
)
from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.expert_finder.display import ExpertDisplay

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def parse_profile_match_response(
    raw: str, candidates: list[dict[str, str]]
) -> str | None:
    """
    Parse ``{"selected_index": N|null}`` (1-based) from model output.

    Returns the matching candidate URL, or None.
    """
    if not candidates:
        return None
    text = (raw or "").strip()
    if not text:
        return None
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        return None
    selected = payload.get("selected_index")
    if selected is None:
        return None
    try:
        index = int(selected)
    except (TypeError, ValueError):
        return None
    if index < 1 or index > len(candidates):
        return None
    url = str(candidates[index - 1].get("url") or "").strip()
    return url or None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            data = json.loads(fenced.group(1))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


class ProfileJudge:
    """Ask Bedrock which social-profile candidate (if any) belongs to the expert."""

    def __init__(self, llm: BedrockLLMService | None = None):
        # Lazy: Bedrock clients are heavier than Brave; skip init when a mock
        # is injected or pick() never runs (e.g. no candidates / search disabled).
        self._llm = llm

    def _get_llm(self) -> BedrockLLMService:
        if self._llm is None:
            self._llm = BedrockLLMService()
        return self._llm

    def pick(
        self,
        *,
        expert: Expert,
        kind: str,
        candidates: list[dict[str, str]],
        expert_name: str | None = None,
    ) -> str | None:
        """Return the chosen candidate URL, or None when no confident match."""
        if not candidates:
            return None
        name = (expert_name or "").strip() or (
            ExpertDisplay.personal_name_for(expert) or (expert.full_name or "")
        ).strip()
        user_prompt = build_profile_match_user_prompt(
            expert_name=name,
            academic_title=(expert.academic_title or "").strip(),
            affiliation=(expert.affiliation or "").strip(),
            expertise=(expert.expertise or "").strip(),
            email=(expert.email or "").strip(),
            notes=(expert.notes or "").strip(),
            profile_kind=kind,
            candidates=candidates,
        )
        try:
            raw = self._get_llm().invoke(
                system_prompt=PROFILE_MATCH_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=256,
                temperature=0.0,
            )
        except Exception:
            logger.exception(
                "Profile match LLM failed expert_id=%s kind=%s",
                getattr(expert, "id", None),
                kind,
            )
            return None
        return parse_profile_match_response(raw, candidates)
