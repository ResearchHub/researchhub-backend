import json
import logging
import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from research_ai.services.expert_display import ExpertDisplay
from research_ai.utils import trimmed_str

logger = logging.getLogger(__name__)


class ExpertFinderJson:
    """Parse and validate expert-finder JSON from LLM completions."""

    @staticmethod
    def _email_is_valid(value: str) -> bool:
        if not value:
            return False
        try:
            validate_email(value)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _normalize_sources(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            t = trimmed_str(item.get("text", ""))
            u = trimmed_str(item.get("url", ""))
            out.append({"text": t, "url": u})
        return out

    @staticmethod
    def parse_text(text: str) -> dict:
        """
        Parse JSON from raw LLM completion.
        """
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        code_block = re.search(r"```(?:json)?\s*(\{[^\}]*\})\s*```", text)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError("Could not extract valid JSON from expert finder LLM response")

    @staticmethod
    def validate_output(obj: Any) -> list[dict[str, Any]]:
        """
        Validate the parsed JSON object. Returns rows for ``upsert_expert_from_parsed_dict``.

        Skips non-dicts, bad emails, and duplicate emails.
        """
        if not isinstance(obj, dict):
            raise ValueError("Expert finder output must be a JSON object")
        raw_experts = obj.get("experts")
        if not isinstance(raw_experts, list):
            raise ValueError("Expert finder output must include an 'experts' array")

        out: list[dict[str, Any]] = []
        seen_emails: set[str] = set()

        for i, row in enumerate(raw_experts):
            if not isinstance(row, dict):
                logger.warning("skipped non-object experts[%s] entry", i)
                continue

            email = ExpertDisplay.normalize_email(trimmed_str(row.get("email", "")))
            if not email:
                logger.warning("skipped experts[%s] with missing or empty email", i)
                continue
            if not ExpertFinderJson._email_is_valid(email):
                logger.warning("skipped experts[%s] with invalid email: %r", i, email)
                continue
            if email in seen_emails:
                logger.warning("skipped duplicate email in experts list: %r", email)
                continue
            seen_emails.add(email)

            row_dict: dict[str, Any] = {
                "email": email,
                "honorific": trimmed_str(row.get("honorific", ""), max_len=64),
                "first_name": trimmed_str(row.get("first_name", ""), max_len=255),
                "middle_name": trimmed_str(row.get("middle_name", ""), max_len=255),
                "last_name": trimmed_str(row.get("last_name", ""), max_len=255),
                "name_suffix": trimmed_str(row.get("name_suffix", ""), max_len=64),
                "academic_title": trimmed_str(
                    row.get("academic_title", ""), max_len=255
                ),
                "affiliation": trimmed_str(row.get("affiliation", "")),
                "expertise": trimmed_str(row.get("expertise", "")),
                "notes": trimmed_str(row.get("notes", "")),
                "sources": ExpertFinderJson._normalize_sources(row.get("sources")),
            }
            out.append(row_dict)

        return out
