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
from math import ceil

from orcid.identifiers import normalize_orcid
from research_ai.constants import (
    EXPERT_FINDER_BATCH_CHASE_RATIO,
    EXPERT_FINDER_DEFAULT_STATE,
    Region,
)
from research_ai.services.agent import Tool, Toolset
from research_ai.services.expert_finder.region_filter import (
    affiliation_mentions_state,
    author_matches_region,
    country_codes_for_region,
    institution_country_codes,
)
from research_ai.services.expert_finder.work_email_lookup import (
    bind_emails_to_authors,
    lookup_work_emails,
    lookup_work_emails_for_page,
    normalize_doi,
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
_MAX_WORKS_PER_CALL = 10
_DEFAULT_WORKS_PER_CALL = 10
# Prefer corresponding + first/last; keep middle coauthors small.
_MAX_AUTHORS_PER_WORK = 8
_MAX_MIDDLE_AUTHORS = 2
_EASY_CHASE_PRIORITIES = frozenset({"high", "medium"})


class ExpertFinderOpenAlexToolset:
    """EF OpenAlex tools: ``search_works`` plus reused author lookup tools.

    Shares ``returned_works`` with the underlying profile toolset so
    ``get_author_works`` provenance and ``search_works`` provenance live in one
    map. Grounded authors map bare id → display_name for a cheap submit check.
    """

    def __init__(
        self,
        *,
        client: OpenAlex | None = None,
        openalex_toolset: OpenAlexToolset | None = None,
        default_publication_years: int = _DEFAULT_PUBLICATION_YEARS,
        region_filter: str = Region.ALL_REGIONS,
        state_filter: str = EXPERT_FINDER_DEFAULT_STATE,
        exclude_work_ids: list[str] | None = None,
        work_email_lookup_fn=None,
    ):
        self._oa = client or OpenAlex()
        self._profile = openalex_toolset or OpenAlexToolset(client=self._oa)
        self._default_publication_years = default_publication_years
        self.region_filter = region_filter or Region.ALL_REGIONS
        self.state_filter = state_filter or EXPERT_FINDER_DEFAULT_STATE
        self._work_email_lookup_fn = work_email_lookup_fn or lookup_work_emails
        self._exclude_work_ids = [
            normalize_openalex_id(wid)
            for wid in (exclude_work_ids or [])
            if normalize_openalex_id(wid)
        ]
        self._exclude_work_id_set = {wid.lower() for wid in self._exclude_work_ids}
        # Share the profile toolset's work provenance map.
        self.returned_works: dict[str, dict] = self._profile.returned_works
        # bare lowercase OpenAlex author id → display_name (may be "").
        self.returned_authors: dict[str, str] = {}
        # Bare OpenAlex author id -> raw author entity (for region grounding).
        self.returned_author_records: dict[str, dict] = {}
        # bare lowercase author id → OpenAlex work ids they appeared on (search_works).
        self.author_work_ids: dict[str, list[str]] = {}
        # Current discovery batch: must email-chase a fraction before paging.
        self.batch_author_ids: set[str] = set()
        self.chased_author_ids: set[str] = set()

    def collected_work_ids(self) -> list[str]:
        """Bare OpenAlex work ids seen via ``search_works`` / author works this run."""
        out: list[str] = []
        seen: set[str] = set()
        for record in self.returned_works.values():
            if not isinstance(record, dict):
                continue
            bare = normalize_openalex_id(
                record.get("openalex_work_id") or record.get("id")
            )
            key = bare.lower()
            if not bare or key in seen:
                continue
            seen.add(key)
            out.append(bare)
        return out

    def work_ids_for_authors(self, author_ids: list[str] | None) -> list[str]:
        """Work ids linked to the given authors during this run (deduped)."""
        out: list[str] = []
        seen: set[str] = set()
        for author_id in author_ids or []:
            bare = normalize_openalex_id(author_id).lower()
            if not bare:
                continue
            for work_id in self.author_work_ids.get(bare) or []:
                key = work_id.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(work_id)
        return out

    def author_work_ids_snapshot(self) -> dict[str, list[str]]:
        """Copy of author => work ids for finder-side filtering after persist."""
        return {
            author_id: list(work_ids)
            for author_id, work_ids in self.author_work_ids.items()
        }

    def mark_author_chased(self, openalex_author_id: str | None) -> bool:
        """Record that we attempted email contact for a batch author."""
        bare = normalize_openalex_id(openalex_author_id).lower()
        if not bare or bare not in self.batch_author_ids:
            return False
        self.chased_author_ids.add(bare)
        return True

    def batch_chase_status(self) -> dict:
        """Progress on email-chasing the current ``search_works`` author batch."""
        batch_n = len(self.batch_author_ids)
        chased_n = len(self.chased_author_ids & self.batch_author_ids)
        required = ceil(batch_n * EXPERT_FINDER_BATCH_CHASE_RATIO) if batch_n else 0
        ratio = (chased_n / batch_n) if batch_n else 1.0
        return {
            "batch_authors": batch_n,
            "chased_authors": chased_n,
            "required_chased": required,
            "required_ratio": EXPERT_FINDER_BATCH_CHASE_RATIO,
            "chase_ratio": round(ratio, 3),
            "ready_for_more_works": chased_n >= required,
        }

    def _replace_author_batch(self, author_ids: list[str]) -> None:
        """Start a new chase batch from the authors on a search_works page."""
        self.batch_author_ids = {
            bare
            for bare in (normalize_openalex_id(aid).lower() for aid in author_ids)
            if bare
        }
        self.chased_author_ids = set()

    def build_tools(self) -> list[Tool]:
        """EF ``search_works`` plus reused author/institution tools."""
        ratio_pct = int(EXPERT_FINDER_BATCH_CHASE_RATIO * 100)
        tools: list[Tool] = [
            Tool(
                name="search_works",
                description=(
                    "Search OpenAlex works by free-text query, restricted to a "
                    "publication-date window (default: last "
                    f"{self._default_publication_years} years). Returns a small "
                    "page of work cards with authorships (may include "
                    "metadata_email and chase_priority). After each page, "
                    f"email-chase at least {ratio_pct}% of easy authors "
                    "(chase_priority high/medium) via email_validate and/or "
                    "web_search with openalex_author_id before calling again."
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
                                f"(default {_DEFAULT_WORKS_PER_CALL}, "
                                f"maximum {_MAX_WORKS_PER_CALL})."
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
        return bool(bare) and bare in self.returned_authors

    def author_identity_matches(
        self, row: dict, *, openalex_author_id: str | None = None
    ) -> bool:
        """True when submitted last name appears in the grounded display name."""
        bare = normalize_openalex_id(
            openalex_author_id or row.get("openalex_author_id")
        ).lower()
        if not bare or bare not in self.returned_authors:
            return False
        last = str(row.get("last_name") or "").strip().casefold()
        if not last:
            return False
        return last in self.returned_authors[bare].casefold()

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

        Prefers a cached record that already has an ORCID value. When the cache is
        missing or only has a null/empty ORCID (common for synthetic records from
        compact tool views), fetches the full OpenAlex author entity.
        """
        bare = normalize_openalex_id(openalex_author_id).lower()
        if not bare:
            return None
        record = self.returned_author_records.get(bare)
        url = self._orcid_url_from_record(record)
        if url:
            return url
        record = self._fetch_and_cache_author(openalex_author_id)
        return self._orcid_url_from_record(record)

    def _fetch_and_cache_author(self, openalex_author_id: str | None) -> dict | None:
        bare = normalize_openalex_id(openalex_author_id)
        if not bare:
            return None
        try:
            # Always use the bare id — full openalex.org URLs break path parsing.
            record = self._oa.get_author(bare)
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

    @staticmethod
    def _orcid_url_from_record(record: dict | None) -> str | None:
        """ORCID public URL from a raw or compact OpenAlex author dict."""
        if not isinstance(record, dict):
            return None
        raw = record.get("orcid")
        if not raw:
            ids = record.get("ids") if isinstance(record.get("ids"), dict) else {}
            raw = ids.get("orcid")
        if not raw:
            observed = record.get("observed_orcids")
            if not observed and isinstance(record.get("ids"), dict):
                observed = record["ids"].get("observed_orcids")
            if isinstance(observed, list) and observed:
                raw = observed[0]
        url, _bare = normalize_orcid(raw)
        return url

    # -- handlers ---------------------------------------------------------

    def _search_works(self, args: dict) -> dict:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            return {"error": "query is required"}

        batch_status = self.batch_chase_status()
        if batch_status["batch_authors"] and not batch_status["ready_for_more_works"]:
            still = max(
                0, batch_status["required_chased"] - batch_status["chased_authors"]
            )
            ratio_pct = int(EXPERT_FINDER_BATCH_CHASE_RATIO * 100)
            return {
                "error": (
                    f"Email-chase at least {ratio_pct}% of the current author "
                    f"batch before another search_works "
                    f"(chased {batch_status['chased_authors']}/"
                    f"{batch_status['batch_authors']}; need "
                    f"{batch_status['required_chased']}, {still} more). "
                    "Call web_search with openalex_author_id for each author."
                ),
                "batch": batch_status,
            }

        try:
            max_results = OpenAlexToolset._bounded_integer(
                (args or {}).get("max_results"),
                default=_DEFAULT_WORKS_PER_CALL,
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
                exclude_openalex_ids=self._exclude_work_ids or None,
            )
        except Exception as exc:  # noqa: BLE001 - miss goes back to the model
            logger.info("OpenAlex search_works failed for %r: %s", query, exc)
            return {"error": f"works search failed: {exc}"}

        payload = []
        email_jobs: list[tuple[str | None, list | None]] = []
        for entity in raw_works or []:
            bare = normalize_openalex_id(entity.get("id")).lower()
            if bare and bare in self._exclude_work_id_set:
                continue
            built = self._work_card_with_authors(entity)
            if built is None:
                continue
            card, doi, authorships = built
            payload.append(card)
            email_jobs.append((doi, authorships))
            if len(payload) >= max_results:
                break

        hits_by_work = lookup_work_emails_for_page(
            email_jobs,
            lookup_fn=self._work_email_lookup_fn,
        )
        easy_author_ids: list[str] = []
        for card, email_hits in zip(payload, hits_by_work, strict=True):
            authors = bind_emails_to_authors(card.get("authors") or [], email_hits)
            for author in authors:
                author["chase_priority"] = self._chase_priority(author)
                author_id = normalize_openalex_id(author.get("openalex_author_id"))
                if author_id and author.get("chase_priority") in _EASY_CHASE_PRIORITIES:
                    easy_author_ids.append(author_id)
            card["authors"] = authors

        # Chase gate tracks easy authors only (corresponding / leads / email hits).
        self._replace_author_batch(easy_author_ids)
        return {
            "works": payload,
            "from_publication_date": from_pub,
            "next_cursor": next_cursor,
            "has_more": bool(next_cursor),
            "batch": self.batch_chase_status(),
        }

    def _work_card_with_authors(
        self, entity: dict
    ) -> tuple[dict, str | None, list] | None:
        """Compact work + authorships; records work/author grounding.

        Email attachment happens at page level (see ``search_works``) so remote
        DOI lookups are parallelized and time-bounded.
        """
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

        authorships = entity.get("authorships") or []
        authors = self._select_authors(
            authorships, openalex_work_id=openalex_work_id or None
        )

        doi = normalize_doi(entity.get("doi") or data.get("source_url")) or None
        card = {
            "title": data["title"],
            "publication_date": data["publication_date"],
            "publication_year": data["publication_year"],
            "source_url": data["source_url"],
            "doi": doi,
            "openalex_work_id": openalex_work_id or None,
            "is_oa": data["is_oa"],
            "authors": authors,
        }
        return card, doi, authorships

    def _select_authors(
        self, authorships: list, *, openalex_work_id: str | None = None
    ) -> list[dict]:
        """Select authors for a work card, capped at ``_MAX_AUTHORS_PER_WORK``.

        Prefer corresponding authors and first/last leads, then a small middle
        slice. Only selected authors are grounded. When OpenAlex omits
        ``author_position`` tags, the first and last list entries are leads.
        """
        cards: list[dict] = []
        for authorship in authorships:
            card = self._authorship_card(authorship)
            if card is None:
                continue
            cards.append(card)
        if not cards:
            return []

        first: list[dict] = []
        middle: list[dict] = []
        last: list[dict] = []
        corresponding: list[dict] = []
        for card in cards:
            if card.get("is_corresponding"):
                corresponding.append(card)
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
        # Reserve slots for corresponding + leads before filling with middle.
        reserved = min(len(corresponding) + 2, _MAX_AUTHORS_PER_WORK)
        middle_pick = middle_pick[: max(0, _MAX_AUTHORS_PER_WORK - reserved)]
        lead_budget = max(
            0, _MAX_AUTHORS_PER_WORK - len(middle_pick) - len(corresponding)
        )
        first_take, last_take = self._allocate_lead_slots(first, last, lead_budget)

        ordered: list[dict] = []
        seen: set[str] = set()
        for card in [*corresponding, *first_take, *middle_pick, *last_take]:
            bare = self._record_author(
                card.get("openalex_author_id"),
                card.get("display_name"),
            )
            if not bare or bare in seen:
                continue
            seen.add(bare)
            self._link_author_to_work(bare, openalex_work_id)
            ordered.append(card)
            if len(ordered) >= _MAX_AUTHORS_PER_WORK:
                break
        return ordered

    @staticmethod
    def _chase_priority(author: dict) -> str:
        """high/medium = worth email-chasing; low = skip unless stuck."""
        if author.get("metadata_email") or author.get("is_corresponding"):
            return "high"
        pos = author.get("author_position")
        has_inst = bool(author.get("institutions"))
        has_orcid = bool(author.get("orcid"))
        if pos in {"first", "last"}:
            return "high" if (has_inst or has_orcid) else "medium"
        if has_orcid and has_inst:
            return "medium"
        return "low"

    def _link_author_to_work(
        self, author_bare_id: str, openalex_work_id: str | None
    ) -> None:
        """Remember that ``author_bare_id`` appeared on ``openalex_work_id``."""
        bare = str(author_bare_id or "").strip().lower()
        work_id = normalize_openalex_id(openalex_work_id)
        if not bare or not work_id:
            return
        bucket = self.author_work_ids.setdefault(bare, [])
        if any(existing.lower() == work_id.lower() for existing in bucket):
            return
        bucket.append(work_id)

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

    def _authorship_card(self, authorship: dict | None) -> dict | None:
        authorship = authorship or {}
        author = authorship.get("author") or {}
        author_id = normalize_openalex_id(author.get("id"))
        if not author_id:
            return None
        institutions: list[str] = []
        country_codes: set[str] = set()
        for inst in authorship.get("institutions") or []:
            inst = inst or {}
            name = str(inst.get("display_name") or "").strip()
            if name and name not in institutions:
                institutions.append(name)
            code = str(inst.get("country_code") or "").strip().upper()
            if code:
                country_codes.add(code)
        orcid = str(author.get("orcid") or "").strip() or None
        matches_region = None
        if self.region_filter == Region.NON_US:
            matches_region = bool(country_codes) and "US" not in country_codes
        else:
            region_codes = country_codes_for_region(self.region_filter)
            if region_codes is not None:
                matches_region = bool(country_codes & region_codes)
        return {
            "openalex_author_id": author.get("id") or author_id,
            "display_name": str(author.get("display_name") or "").strip() or None,
            "author_position": authorship.get("author_position") or None,
            "is_corresponding": bool(authorship.get("is_corresponding")),
            "orcid": orcid,
            "institutions": institutions,
            "matches_region": matches_region,
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
        bare = self._record_author(author_id, view.get("display_name"))
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
                "affiliations": self._affiliations_for_cache(view),
            }
            if (
                self.region_filter != Region.ALL_REGIONS
                and not institution_country_codes(synthetic)
            ):
                fetched = self._fetch_and_cache_author(author_id)
                if fetched is None:
                    self.returned_author_records[bare] = synthetic
            else:
                self.returned_author_records[bare] = synthetic

        record = self.returned_author_records.get(bare) or {}
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

    @staticmethod
    def _affiliations_for_cache(view: dict) -> list[dict]:
        """OpenAlex-shaped affiliations, keeping compact-view country codes."""
        rows: list[dict] = []
        for item in view.get("affiliations") or []:
            if not isinstance(item, dict):
                continue
            inst = item.get("institution") if "institution" in item else item
            inst = inst or {}
            name = str(inst.get("display_name") or "").strip()
            code = str(inst.get("country_code") or "").strip().upper() or None
            if not name and not code:
                continue
            rows.append(
                {
                    "institution": {
                        "display_name": name or None,
                        "country_code": code,
                    }
                }
            )
        if rows:
            return rows
        return [
            {"institution": {"display_name": name}}
            for name in (view.get("institutions") or [])
            if name
        ]

    def _cache_author_record(self, record: dict) -> str:
        bare = self._record_author(record.get("id"), record.get("display_name"))
        if bare:
            self.returned_author_records[bare] = record
        return bare

    def _record_author(
        self,
        openalex_author_id: str | None,
        display_name: str | None = None,
    ) -> str:
        """Remember author id → display_name; return bare lowercase id or empty."""
        bare = normalize_openalex_id(openalex_author_id).lower()
        if not bare:
            return ""
        name = str(display_name or "").strip()
        # Keep a prior name if this call only had an id.
        if not name:
            name = self.returned_authors.get(bare, "")
        self.returned_authors[bare] = name
        return bare

    def _default_from_publication_date(self) -> str:
        years = max(1, int(self._default_publication_years))
        # Approximate calendar years.
        start = date.today() - timedelta(days=365 * years)
        return start.strftime("%Y-%m-%d")
