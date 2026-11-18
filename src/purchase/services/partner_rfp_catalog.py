"""Read a partner's finalized topic catalog without touching Django or the DB."""

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_RFPS = 2000


@dataclass(frozen=True)
class PartnerRfpTopic:
    topic: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    image: str | None = None
    research_flag: str = ""

    def source_id(self, partner_organization: str) -> str:
        # Topic is the import identity. Freeze it after the first import; titles,
        # summaries and keyword lists may change without creating a new post.
        digest = hashlib.sha256(self.topic.casefold().encode()).hexdigest()
        partner = validate_partner_organization(partner_organization)
        return f"partner:{partner}:{digest}"


def validate_partner_organization(value: str) -> str:
    """A stable namespace, kept short enough for external_source_id's limit."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,47}", value):
        raise ValueError(
            "Partner organization must be 1–48 lowercase letters, digits, "
            "dots, hyphens or underscores, starting with a letter or digit"
        )
    return value


def validate_https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Image must be a permanent public HTTPS URL without a query")
    return value


def read_catalog(
    path: str | Path,
    *,
    partner_organization: str,
) -> list[PartnerRfpTopic]:
    validate_partner_organization(partner_organization)
    topics = []
    seen = set()
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"Topic", "Title", "Summary", "Keywords"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV requires columns: {', '.join(sorted(required))}")
        for line, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            try:
                topic = (row["Topic"] or "").strip()
                title = (row["Title"] or "").strip()
                # The supplied CSV contains literal backslash-n separators.
                summary = (row["Summary"] or "").replace("\\n", "\n").strip()
                keywords = tuple(
                    dict.fromkeys(
                        word.strip()
                        for word in (row["Keywords"] or "").split(",")
                        if word.strip()
                    )
                )
                image = (row.get("Image") or "").strip() or None
                if not topic or topic.casefold() in seen:
                    raise ValueError("Topic must be nonblank and unique")
                if not 20 <= len(title) <= 200 or "\n" in title or "\r" in title:
                    raise ValueError("Title must be one line, 20–200 characters")
                if not 50 <= len(summary) <= 2000:
                    raise ValueError("Summary must be 50–2,000 characters")
                if re.search(r"https?://|www\.|\[[^]]+\]\(|<[^>]+>", summary):
                    raise ValueError("Summary must be plain text without links or HTML")
                if len(keywords) > 50 or any(len(word) > 100 for word in keywords):
                    raise ValueError(
                        "Use at most 50 keywords, each at most 100 characters"
                    )
                if image:
                    validate_https_url(image)
                topics.append(
                    PartnerRfpTopic(
                        topic=topic,
                        title=title,
                        summary=summary,
                        keywords=keywords,
                        image=image,
                        research_flag=(row.get("Research Flag") or "").strip(),
                    )
                )
                seen.add(topic.casefold())
            except ValueError as error:
                raise ValueError(f"CSV row {line}: {error}") from error
    if not topics:
        raise ValueError("CSV contains no topics")
    if len(topics) > MAX_RFPS:
        raise ValueError(f"Catalog exceeds {MAX_RFPS} RFPs")
    return topics


def permanent_rfp_id(post_id: int) -> str:
    """The post PK is the public RFP identity, NOT Grant.id or a mutable slug."""
    return str(post_id)
