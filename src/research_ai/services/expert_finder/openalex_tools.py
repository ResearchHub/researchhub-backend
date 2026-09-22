"""OpenAlex tools for the expert-finder agent.

Works-first discovery: ``search_works`` finds recent papers by keyword, then the
agent drills into authors via the shared profile tools (``get_author``,
``search_authors``, ``get_author_works``, ``search_institutions``).

When a ``region_filter`` is set, author tool results are annotated with
``matches_region`` (and optional soft ``matches_state`` for US), and raw author
records are cached so server-side grounding can hard-drop out-of-region rows.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from orcid.identifiers import normalize_orcid
from research_ai.constants import EXPERT_FINDER_DEFAULT_STATE, Region
from research_ai.services.agent import Tool, Toolset
from research_ai.services.expert_finder.region_filter import (
    affiliation_mentions_state,
    author_matches_region,
    institution_country_codes,
)
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex, Work, normalize_openalex_id

logger = logging.getLogger(__name__)

# Author/institution tools reused from the profile OpenAlex toolset.
_REUSED_AUTHOR_TOOLS = frozenset(
    {
        "search_institutions",
        "search_authors",
        "get_author",
        "get_author_works",
    }
)

_DEFAULT_PUBLICATION_YEARS = 5
_MAX_WORKS_PER_CALL = 25
_MAX_AUTHORS_PER_WORK = 20
_MAX_MIDDLE_AUTHORS = 5


class ExpertFinderOpenAlexToolset:
    """EF OpenAlex tools: ``search_works`` plus reused author lookup tools.

    Shares ``returned_works`` with the underlying profile toolset so
    ``get_author_works`` provenance and ``search_works`` provenance live in one
    map.
    """

    def __init__(
        self,
        *,
        client: OpenAlex | None = None,
        openalex_toolset: OpenAlexToolset | None = None,
        default_publication_years: int = _DEFAULT_PUBLICATION_YEARS,
        region_filter: str = Region.ALL_REGIONS,
        state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
    ):
        self._oa = client or OpenAlex()
        self._profile = openalex_toolset or OpenAlexToolset(client=self._oa)
        self._default_publication_years = default_publication_years
        self.region_filter = region_filter or Region.ALL_REGIONS
        self.state_filter = state_filter or EXPERT_FINDER_DEFAULT_STATE
        # Share the profile toolset's work provenance map.
        self.returned_works: dict[str, dict] = self._profile.returned_works
        self.returned_author_ids: set[str] = set()
        # Bare OpenAlex author id -> raw author entity (for region grounding).
        self.returned_author_records: dict[str, dict] = {}

    def build_tools(self) -> list[Tool]:
        """EF ``search_works`` plus reused author/institution tools."""
        tools: list[Tool] = [
            Tool(
                name="search_works",
                description=(
                    "Search OpenAlex works by free-text query, restricted to a "
                    "publication-date window (default: last "
                    f"{self._default_publication_years} years). Returns compact "
                    "work cards with authorships. Follow next_cursor for more "
                    "pages. Only authors returned here (or via get_author / "
                    "search_authors) may be submitted later."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Keywords / topic phrase for works search."
                            ),
                        },
                        "from_publication_date": {
                            "type": "string",
                            "description": (
                                "YYYY-MM-DD lower bound on publication date. "
                                "Omit to use the default recent window."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_WORKS_PER_CALL,
                            "description": (
                                "Works per page "
                                f"(default 10, maximum {_MAX_WORKS_PER_CALL})."
                            ),
                        },
                        "cursor": {
                            "type": "string",
                            "description": (
                                "Opaque next_cursor from the prior page. Omit "
                                "for the first page."
                            ),
                        },
                    },
                    "required": ["query"],
                },
                handler=self._search_works,
            )
        ]
        tools.extend(
            self._wrap_for_author_grounding(tool)
            for tool in self._profile.build_tools()
            if tool.name in _REUSED_AUTHOR_TOOLS
        )
        return tools

    def as_toolset(self) -> Toolset:
        """Wrap ``build_tools()`` in a core ``Toolset`` for the agent."""
        return Toolset(self.build_tools())

    def has_returned_author(self, openalex_author_id: str | None) -> bool:
        """True when ``openalex_author_id`` was returned by a tool this run."""
        bare = normalize_openalex_id(openalex_author_id).lower()
        return bool(bare) and bare in self.returned_author_ids

    def resolve_author_record(self, openalex_author_id: str | None) -> dict | None:
        """Return a cached or freshly fetched OpenAlex author entity."""
        bare = normalize_openalex_id(openalex_author_id).lower()
        if not bare:
            return None
        cached = self.returned_author_records.get(bare)
        if cached is not None:
            return cached
        return self._fetch_and_cache_author(openalex_author_id)

    def resolve_orcid_url(self, openalex_author_id: str | None) -> str | None:
        """Public ORCID URL for an author, when OpenAlex has one.

        Uses the cached record when it already carries an ``orcid`` key (including
        ``None``). Otherwise fetches the full OpenAlex author — needed when the
        author was grounded only via ``search_works`` authorships.
        """
        bare = normalize_openalex_id(openalex_author_id).lower()
        if not bare:
            return None
        record = self.returned_author_records.get(bare)
        if record is None or "orcid" not in record:
            record = self._fetch_and_cache_author(openalex_author_id)
        if not isinstance(record, dict):
            return None
        url, _bare = normalize_orcid(record.get("orcid"))
        return url

    def _fetch_and_cache_author(self, openalex_author_id: str | None) -> dict | None:
        try:
            record = self._oa.get_author(openalex_author_id)
        except Exception as exc:  # noqa: BLE001 - grounding is best-effort
            logger.info(
                "OpenAlex get_author failed during resolve for %r: %s",
                openalex_author_id,
                exc,
            )
            return None
        if not isinstance(record, dict) or not record.get("id"):
            return None
        self._cache_author_record(record)
        return record

    # -- handlers ---------------------------------------------------------

    def _search_works(self, args: dict) -> dict:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        try:
            max_results = OpenAlexToolset._bounded_integer(
                (args or {}).get("max_results"),
                default=10,
                minimum=1,
                maximum=_MAX_WORKS_PER_CALL,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        from_pub = str((args or {}).get("from_publication_date") or "").strip()
        if not from_pub:
            from_pub = self._default_from_publication_date()
        cursor = str((args or {}).get("cursor") or "").strip() or "*"

        try:
            raw_works, next_cursor = self._oa.get_works(
                search=query,
                from_publication_date=from_pub,
                next_cursor=cursor,
                batch_size=max_results,
            )
        except Exception as exc:  # noqa: BLE001 - miss goes back to the model
            logger.info("OpenAlex search_works failed for %r: %s", query, exc)
            return {"error": f"works search failed: {exc}"}

        payload = []
        for entity in raw_works or []:
            card = self._work_card_with_authors(entity)
            if card is None:
                continue
            payload.append(card)
            if len(payload) >= max_results:
                break
        return {
            "works": payload,
            "from_publication_date": from_pub,
            "next_cursor": next_cursor,
            "has_more": bool(next_cursor),
        }

    def _work_card_with_authors(self, entity: dict) -> dict | None:
        """Compact work + authorships; records work/author grounding."""
        work = Work.from_openalex(entity)
        if work is None:
            return None
        data = work.as_dict()
        openalex_work_id = normalize_openalex_id(entity.get("id"))
        if data["source_url"]:
            # Keep full record for later grounding (same map as get_author_works).
            record = {
                **data,
                "openalex_work_id": openalex_work_id or None,
            }
            self.returned_works[data["source_url"]] = record
            if openalex_work_id:
                # Also key by OpenAlex URL so either form resolves.
                oa_url = str(entity.get("id") or "").strip()
                if oa_url and oa_url not in self.returned_works:
                    self.returned_works[oa_url] = record

        authors = self._select_authors(entity.get("authorships") or [])

        return {
            "title": data["title"],
            "publication_date": data["publication_date"],
            "publication_year": data["publication_year"],
            "source_url": data["source_url"],
            "openalex_work_id": openalex_work_id or None,
            "is_oa": data["is_oa"],
            "authors": authors,
        }

    def _select_authors(self, authorships: list) -> list[dict]:
        """Select authors for a work card, capped at ``_MAX_AUTHORS_PER_WORK``.

        Prefer first/last leads, then up to ``_MAX_MIDDLE_AUTHORS`` middle
        coauthors (in list order). Only selected authors are grounded.
        When OpenAlex omits ``author_position`` tags, the
        first and last list entries are treated as leads.
        """
        cards: list[dict] = []
        for authorship in authorships:
            card = self._authorship_card(authorship)
            if card is not None:
                cards.append(card)
        if not cards:
            return []

        first: list[dict] = []
        middle: list[dict] = []
        last: list[dict] = []
        for card in cards:
            pos = card.get("author_position")
            if pos == "first":
                first.append(card)
            elif pos == "last":
                last.append(card)
            else:
                middle.append(card)

        if not first and not last:
            first = [cards[0]]
            last = [cards[-1]] if len(cards) > 1 else []
            middle = cards[1:-1] if len(cards) > 2 else []

        middle_pick = middle[:_MAX_MIDDLE_AUTHORS]
        lead_budget = max(0, _MAX_AUTHORS_PER_WORK - len(middle_pick))
        first_take, last_take = self._allocate_lead_slots(first, last, lead_budget)

        ordered: list[dict] = []
        seen: set[str] = set()
        for card in [*first_take, *middle_pick, *last_take]:
            bare = normalize_openalex_id(card.get("openalex_author_id")).lower()
            if not bare or bare in seen:
                continue
            seen.add(bare)
            self._record_author_id(bare)
            ordered.append(card)
            if len(ordered) >= _MAX_AUTHORS_PER_WORK:
                break
        return ordered

    @staticmethod
    def _allocate_lead_slots(
        first: list[dict], last: list[dict], budget: int
    ) -> tuple[list[dict], list[dict]]:
        if budget <= 0:
            return [], []
        if first and last:
            # Aim for an even split; leftover slot prefers last (senior).
            first_n = min(len(first), budget // 2)
            last_n = min(len(last), budget - first_n)
            first_n = min(len(first), budget - last_n)
            return first[:first_n], last[:last_n]
        if first:
            return first[:budget], []
        return [], last[:budget]

    @staticmethod
    def _authorship_card(authorship: dict | None) -> dict | None:
        authorship = authorship or {}
        author = authorship.get("author") or {}
        author_id = normalize_openalex_id(author.get("id"))
        if not author_id:
            return None
        institutions: list[str] = []
        for inst in authorship.get("institutions") or []:
            name = str((inst or {}).get("display_name") or "").strip()
            if name and name not in institutions:
                institutions.append(name)
        return {
            "openalex_author_id": author.get("id") or author_id,
            "display_name": str(author.get("display_name") or "").strip() or None,
            "author_position": authorship.get("author_position") or None,
            "institutions": institutions,
        }

    def _wrap_for_author_grounding(self, tool: Tool) -> Tool:
        """Reuse a profile tool handler while recording returned author ids."""
        original = tool.handler

        def handler(args: dict) -> dict:
            result = original(args or {})
            self._record_authors_from_tool_result(tool.name, result)
            return result

        return Tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            handler=handler,
            is_terminal=tool.is_terminal,
            eager_input_streaming=tool.eager_input_streaming,
        )

    def _record_authors_from_tool_result(self, tool_name: str, result: dict) -> None:
        if not isinstance(result, dict) or result.get("error"):
            return
        if tool_name == "get_author":
            self._annotate_and_cache_author_view(result)
            return
        if tool_name == "search_authors":
            for row in result.get("results") or []:
                if isinstance(row, dict):
                    self._annotate_and_cache_author_view(row)

    def _annotate_and_cache_author_view(self, view: dict) -> None:
        """Cache grounding id, attach region/state hints, keep a synthetic record."""
        author_id = view.get("openalex_author_id")
        bare = self._record_author_id(author_id)
        if not bare:
            return

        # Rebuild a minimal entity for region checks from the compact view when
        # we do not already have a fuller raw record from OpenAlex.
        if bare not in self.returned_author_records:
            synthetic = {
                "id": author_id,
                "orcid": view.get("orcid"),
                "last_known_institutions": list(
                    view.get("last_known_institutions") or []
                ),
                "affiliations": [
                    {"institution": {"display_name": name}}
                    for name in (view.get("institutions") or [])
                    if name
                ],
            }
            self.returned_author_records[bare] = synthetic

        record = self.returned_author_records[bare]
        country_codes = sorted(institution_country_codes(record))
        view["country_codes"] = country_codes
        if self.region_filter != Region.ALL_REGIONS:
            view["matches_region"] = author_matches_region(record, self.region_filter)
        if (
            self.region_filter == Region.US
            and self.state_filter != EXPERT_FINDER_DEFAULT_STATE
        ):
            affiliation_text = " ".join(
                str(x or "")
                for x in [
                    *(view.get("institutions") or []),
                    *[
                        (inst or {}).get("display_name")
                        for inst in (view.get("last_known_institutions") or [])
                    ],
                ]
            )
            view["matches_state"] = affiliation_mentions_state(
                affiliation_text, self.state_filter
            )

    def _cache_author_record(self, record: dict) -> str:
        bare = self._record_author_id(record.get("id"))
        if bare:
            self.returned_author_records[bare] = record
        return bare

    def _record_author_id(self, value: str | None) -> str:
        bare = normalize_openalex_id(value).lower()
        if bare:
            self.returned_author_ids.add(bare)
        return bare

    def _default_from_publication_date(self) -> str:
        years = max(1, int(self._default_publication_years))
        # Approximate calendar years.
        start = date.today() - timedelta(days=365 * years)
        return start.strftime("%Y-%m-%d")
