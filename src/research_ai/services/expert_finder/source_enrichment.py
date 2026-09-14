import logging
import re
from urllib.parse import parse_qs, urlparse

from research_ai.models import Expert
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.expert_finder.profile_match import ProfileJudge
from utils.brave_search import BraveSearch

logger = logging.getLogger(__name__)


_LINKEDIN_RE = re.compile(
    r"https?://(?:[\w-]+\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?",
    re.IGNORECASE,
)
_X_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/?",
    re.IGNORECASE,
)
_SCHOLAR_USER_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Non-profile X path segments (not identity matching — URL shape only).
_X_HANDLE_BLOCKLIST = frozenset(
    {
        "home",
        "share",
        "intent",
        "search",
        "explore",
        "i",
        "settings",
        "login",
        "signup",
        "hashtag",
        "messages",
        "notifications",
        "compose",
    }
)

_WEB_PROFILE_KINDS = ("linkedin", "x", "google_scholar")
_WEB_PROFILE_LABELS = {
    "linkedin": "LinkedIn",
    "x": "X",
    "google_scholar": "Google Scholar",
}
_WEB_PROFILE_QUERY_SUFFIX = {
    "linkedin": "linkedin",
    "x": "twitter",
    "google_scholar": "google scholar",
}
_PROFILE_CANDIDATE_LIMIT = 3


def _normalize_url_key(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _url_from_source(item) -> str:
    """Extract a URL string from a sources list entry (dict or bare string)."""
    if isinstance(item, dict):
        return str(item.get("url") or "").strip()
    if isinstance(item, str):
        return item.strip()
    return ""


def source_kind_for_url(url: str) -> str | None:
    """Classify a URL into a profile kind via host/path, or None for generic sources."""
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()

    if host == "orcid.org" or host.endswith(".orcid.org"):
        return "orcid"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin" if "/in/" in path else None
    if host in {"x.com", "twitter.com"} or host.endswith((".x.com", ".twitter.com")):
        return "x"
    if "scholar.google." in host and "user=" in query:
        return "google_scholar"
    return None


def source_kinds_present(sources: list) -> set[str]:
    """Return which known profile kinds already appear in ``sources``."""
    kinds: set[str] = set()
    for item in sources or []:
        kind = source_kind_for_url(_url_from_source(item))
        if kind:
            kinds.add(kind)
    return kinds


def canonicalize_sources_for_expert(sources: list) -> list:
    """Keep at most one ORCID / LinkedIn / X / Google Scholar URL; preserve others."""
    out: list = []
    seen_kinds: set[str] = set()
    for item in sources or []:
        kind = source_kind_for_url(_url_from_source(item))
        if kind:
            if kind in seen_kinds:
                continue
            seen_kinds.add(kind)
        out.append(item)
    return out


def merge_sources(existing: list, additions: list[dict[str, str]]) -> list:
    """Append new ``{text, url}`` entries; at most one URL per profile kind."""
    out: list = list(existing) if isinstance(existing, list) else []
    seen_urls = {
        _normalize_url_key(_url_from_source(item))
        for item in out
        if _url_from_source(item)
    }
    present_kinds = source_kinds_present(out)
    for entry in additions:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        text = str(entry.get("text") or "").strip()
        key = _normalize_url_key(url)
        if not key or key in seen_urls:
            continue
        kind = source_kind_for_url(url)
        if kind and kind in present_kinds:
            continue
        seen_urls.add(key)
        if kind:
            present_kinds.add(kind)
        out.append({"text": text or url, "url": url})
    return out


def canonicalize_linkedin_url(url: str) -> str | None:
    match = _LINKEDIN_RE.search(url or "")
    if not match:
        return None
    slug = match.group(1).rstrip("/")
    if slug.lower() in {"", "pub", "dir"}:
        return None
    return f"https://www.linkedin.com/in/{slug}"


def canonicalize_x_url(url: str) -> str | None:
    match = _X_RE.search(url or "")
    if not match:
        return None
    handle = match.group(1)
    if handle.lower() in _X_HANDLE_BLOCKLIST:
        return None
    return f"https://x.com/{handle}"


def canonicalize_scholar_url(url: str) -> str | None:
    """Normalize a Google Scholar citations profile URL, or None if not a profile."""
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    if "scholar.google." not in host:
        return None
    if "/citations" not in (parsed.path or "").lower():
        return None
    user = (parse_qs(parsed.query).get("user") or [None])[0]
    if not user or not _SCHOLAR_USER_RE.fullmatch(user):
        return None
    return f"https://scholar.google.com/citations?user={user}"


def _query_context_bits(title: str = "", affiliation: str = "") -> list[str]:
    """Optional title/affiliation disambiguators for social profile searches."""
    bits: list[str] = []
    title = " ".join((title or "").split())
    if title:
        bits.append(title)
    aff = " ".join((affiliation or "").split())
    if aff:
        # Keep affiliation short so Brave ranking stays person-focused.
        bits.append(aff[:80].strip())
    return bits


def build_web_profile_query(
    kind: str, name: str, title: str = "", affiliation: str = ""
) -> str:
    """
    Natural-language profile search: ``Name Title Affiliation <suffix>``.
    """
    suffix = _WEB_PROFILE_QUERY_SUFFIX.get(kind)
    if not suffix:
        raise ValueError(f"unsupported social kind: {kind}")
    name = " ".join((name or "").split())
    parts = [name, *_query_context_bits(title, affiliation), suffix]
    return " ".join(p for p in parts if p)


def _canonicalize_web_profile_url(kind: str, url: str) -> str | None:
    if kind == "linkedin":
        return canonicalize_linkedin_url(url)
    if kind == "x":
        return canonicalize_x_url(url)
    if kind == "google_scholar":
        return canonicalize_scholar_url(url)
    raise ValueError(f"unsupported social kind: {kind}")


def collect_profile_candidates(
    results: list[dict],
    *,
    kind: str,
    limit: int = _PROFILE_CANDIDATE_LIMIT,
) -> list[dict[str, str]]:
    """
    Project Brave hits into up to ``limit`` unique canonical profile candidates.

    Does not decide identity — that is the profile-match LLM's job.
    """
    if kind not in _WEB_PROFILE_KINDS:
        raise ValueError(f"unsupported social kind: {kind}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in results or []:
        if not isinstance(row, dict):
            continue
        if len(out) >= limit:
            break
        raw_url = str(row.get("url") or "").strip()
        canon = _canonicalize_web_profile_url(kind, raw_url)
        if not canon:
            continue
        key = _normalize_url_key(canon)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "url": canon,
                "title": str(row.get("title") or "").strip(),
                "description": str(row.get("description") or "").strip(),
            }
        )
    return out


def _search_person_name(expert: Expert) -> str:
    """Name used in Brave queries: first / middle / last via ``personal_name_for``."""
    name = ExpertDisplay.personal_name_for(expert).strip()
    if name:
        return name
    return (expert.full_name or "").strip()


class SourceEnrichmentService:
    """Best-effort LinkedIn / X / Scholar enrichment after finder persist."""

    def __init__(
        self,
        *,
        web_search: BraveSearch | None = None,
        profile_judge: ProfileJudge | None = None,
        max_web_searches: int = 120,
    ):
        self._web_search = web_search or BraveSearch()
        self._profile_judge = profile_judge or ProfileJudge()
        self.max_web_searches = max_web_searches
        self._web_searches_used = 0

    def enrich_experts(self, experts: list[Expert]) -> int:
        """Enrich each expert in order. Returns how many experts had sources updated."""
        updated = 0
        for expert in experts:
            try:
                if self.enrich_expert(expert):
                    updated += 1
            except Exception:
                logger.exception(
                    "Source enrichment failed expert_id=%s", getattr(expert, "id", None)
                )
        return updated

    def enrich_expert(self, expert: Expert) -> bool:
        """
        Mutate and save ``expert.sources`` when new social profile links are found.

        Returns True when sources changed.
        """
        original = expert.sources if isinstance(expert.sources, list) else []
        sources = canonicalize_sources_for_expert(original)
        sources = self._enrich_social_from_web_search(expert, sources)
        sources = canonicalize_sources_for_expert(sources)
        if sources == original:
            return False
        expert.sources = sources
        expert.save(update_fields=["sources", "updated_date"])
        return True

    def _enrich_social_from_web_search(self, expert: Expert, sources: list) -> list:
        kinds = source_kinds_present(sources)
        missing = [kind for kind in _WEB_PROFILE_KINDS if kind not in kinds]
        if not missing:
            return sources
        name = _search_person_name(expert)
        if not name:
            return sources
        if not self._web_search.configured:
            return sources

        title = (expert.academic_title or "").strip()
        affiliation = (expert.affiliation or "").strip()
        additions: list[dict[str, str]] = []
        for kind in missing:
            url = self._web_search_profile(
                expert=expert,
                kind=kind,
                name=name,
                title=title,
                affiliation=affiliation,
            )
            if url:
                additions.append({"text": _WEB_PROFILE_LABELS[kind], "url": url})
        return merge_sources(sources, additions)

    def _web_search_profile(
        self,
        *,
        expert: Expert,
        kind: str,
        name: str,
        title: str,
        affiliation: str = "",
    ) -> str | None:
        if self._web_searches_used >= self.max_web_searches:
            return None
        query = build_web_profile_query(kind, name, title, affiliation)
        self._web_searches_used += 1
        try:
            results = self._web_search.search(query, count=5)
        except Exception:
            return None
        candidates = collect_profile_candidates(results, kind=kind)
        if not candidates:
            return None
        return self._profile_judge.pick(
            expert=expert,
            kind=kind,
            candidates=candidates,
            expert_name=name,
        )
