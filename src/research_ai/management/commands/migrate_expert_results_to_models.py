"""
One-time backfill: ExpertSearch.expert_results JSON -> Expert + SearchExpert rows.

Unstructured ``name`` fields are split into honorific / first / middle / last / suffix.
Name parsing helpers below are migration-only; delete this file after backfill is complete.

Usage:
  cd src && uv run python manage.py migrate_expert_results_to_models --dry-run
  cd src && uv run python manage.py migrate_expert_results_to_models
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from research_ai.models import ExpertSearch, SearchExpert
from research_ai.services.expert_display import normalize_expert_email
from research_ai.services.expert_persist import upsert_expert_from_parsed_dict

_CREDENTIAL_TOKENS = frozenset(
    {
        "phd",
        "md",
        "mba",
        "jd",
        "dds",
        "dvm",
        "rn",
        "mph",
        "msc",
        "ms",
        "ma",
        "jr",
        "sr",
        "ii",
        "iii",
        "iv",
        "esq",
        "frcp",
        "facp",
    }
)


def _is_likely_credentials(segment: str) -> bool:
    t = (segment or "").strip()
    if not t or len(t) > 64:
        return False
    norm = re.sub(r"[^a-z0-9]+", "", t.lower())
    return norm in _CREDENTIAL_TOKENS


def _strip_trailing_suffixes(s: str) -> tuple[str, str]:
    """Repeatedly peel ', PhD'-style trailing segments; return (core, suffix joined)."""
    name_suffix = ""
    rest = (s or "").strip()
    while "," in rest:
        left, right = rest.rsplit(",", 1)
        right_stripped = right.strip()
        if not _is_likely_credentials(right_stripped):
            break
        name_suffix = (
            f"{right_stripped}, {name_suffix}".rstrip(", ")
            if name_suffix
            else right_stripped
        )
        rest = left.strip()
    return rest, name_suffix


_HONORIFIC_RAW = frozenset(
    {
        "dr",
        "prof",
        "professor",
        "mr",
        "mrs",
        "ms",
        "miss",
    }
)


def _normalize_honorific(token: str) -> str:
    t = token.strip()
    low = t.lower().rstrip(".")
    if low == "professor":
        return "Prof."
    if low == "prof":
        return "Prof."
    if low == "dr":
        return "Dr."
    if low in ("mr", "mrs", "ms", "miss"):
        return t[:1].upper() + low[1:] + ("." if not t.endswith(".") else "")
    return t


def _strip_leading_honorific(tokens: list[str]) -> tuple[str, list[str]]:
    if not tokens:
        return "", tokens
    t0 = tokens[0].lower().rstrip(".")
    if t0 in _HONORIFIC_RAW:
        return _normalize_honorific(tokens[0]), tokens[1:]
    return "", tokens


def _parse_expert_full_name(raw: str) -> dict[str, str]:
    """Split a free-form name into honorific, first, middle, last, name_suffix."""
    result: dict[str, str] = {
        "honorific": "",
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "name_suffix": "",
    }
    s = (raw or "").strip()
    if not s:
        return result

    core, suffix = _strip_trailing_suffixes(s)
    result["name_suffix"] = (suffix or "")[:64]

    if "," in core:
        left, right = core.split(",", 1)
        left, right = left.strip(), right.strip()
        if left and right:
            rest_tokens = right.split()
            hon, rest_tokens = _strip_leading_honorific(rest_tokens)
            result["honorific"] = hon[:64]
            result["last_name"] = left[:255]
            if rest_tokens:
                result["first_name"] = rest_tokens[0][:255]
                if len(rest_tokens) > 1:
                    result["middle_name"] = " ".join(rest_tokens[1:])[:255]
            return result

    tokens = core.split()
    hon, tokens = _strip_leading_honorific(tokens)
    result["honorific"] = hon[:64]
    if not tokens:
        return result
    if len(tokens) == 1:
        result["first_name"] = tokens[0][:255]
    elif len(tokens) == 2:
        result["first_name"], result["last_name"] = tokens[0][:255], tokens[1][:255]
    else:
        result["first_name"] = tokens[0][:255]
        result["last_name"] = tokens[-1][:255]
        result["middle_name"] = " ".join(tokens[1:-1])[:255]
    return result


def _merge_legacy_name_into_payload(target: dict, full_name: str) -> None:
    """Fill blank name keys from unstructured ``name`` string."""
    if (target.get("first_name") or "").strip() and (
        target.get("last_name") or ""
    ).strip():
        return
    full = (full_name or "").strip()
    if not full:
        return
    parsed = _parse_expert_full_name(full)
    for key in ("honorific", "first_name", "middle_name", "last_name", "name_suffix"):
        val = parsed.get(key) or ""
        if val and not (target.get(key) or "").strip():
            target[key] = val


def _payload_from_legacy_expert_result_row(item: dict) -> dict:
    """One ``expert_results`` JSON object -> dict for upsert."""
    email = normalize_expert_email(item.get("email") or "")
    payload = {
        "email": email,
        "honorific": item.get("honorific") or "",
        "first_name": item.get("first_name") or "",
        "middle_name": item.get("middle_name") or "",
        "last_name": item.get("last_name") or "",
        "name_suffix": item.get("name_suffix") or "",
        "academic_title": item.get("academic_title") or item.get("title") or "",
        "title": item.get("title") or "",
        "affiliation": item.get("affiliation") or "",
        "expertise": item.get("expertise") or "",
        "notes": item.get("notes") or "",
        "sources": item.get("sources") if isinstance(item.get("sources"), list) else [],
    }
    _merge_legacy_name_into_payload(payload, (item.get("name") or "").strip())
    return payload


class Command(BaseCommand):
    help = (
        "Backfill Expert + SearchExpert from legacy ExpertSearch.expert_results JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts only; do not write.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        qs = ExpertSearch.objects.exclude(expert_results=[]).order_by("id")
        total_searches = 0
        total_rows = 0
        skipped = 0

        for search in qs.iterator(chunk_size=50):
            raw = search.expert_results or []
            if not raw:
                continue
            if search.search_experts.exists():
                self.stdout.write(
                    f"Skip search {search.id}: already has SearchExpert rows."
                )
                continue
            total_searches += 1
            if dry_run:
                total_rows += len([x for x in raw if isinstance(x, dict)])
                continue

            with transaction.atomic():
                position = 0
                seen_email = set()
                for item in raw:
                    if not isinstance(item, dict):
                        skipped += 1
                        continue
                    legacy = _payload_from_legacy_expert_result_row(item)
                    email = legacy["email"]
                    if not email or email in seen_email:
                        skipped += 1
                        continue
                    seen_email.add(email)
                    try:
                        expert = upsert_expert_from_parsed_dict(legacy)
                    except ValueError:
                        skipped += 1
                        continue
                    SearchExpert.objects.update_or_create(
                        expert_search_id=search.id,
                        expert_id=expert.id,
                        defaults={"position": position},
                    )
                    position += 1
                    total_rows += 1

        self.stdout.write(
            self.style.NOTICE(
                f"searches_touched={total_searches} rows_written={total_rows} "
                f"skipped={skipped} dry_run={dry_run}"
            )
        )
