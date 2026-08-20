"""Grant discovery tools for the notebook chat agent."""

import logging

from purchase.services.grant_search_service import GrantSearchService
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.agent import Tool, Toolset

logger = logging.getLogger(__name__)

SEARCH_GRANTS = "search_grants"
GET_GRANT_DETAILS = "get_grant_details"
_MAX_QUERY_CHARS = 500
_MAX_RESULTS = 5
_MAX_SUMMARY_CHARS = 300
_MAX_DESCRIPTION_CHARS = 6000
_MAX_POST_CONTENT_CHARS = 6000


class GrantSearchToolset:
    """Search application-ready grants as the conversation's user."""

    def __init__(
        self,
        *,
        user,
        service: GrantSearchService | None = None,
    ):
        self._user = user
        self._service = service or GrantSearchService()

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=SEARCH_GRANTS,
                description=(
                    "Search ResearchHub for active grants/RFPs relevant to a "
                    "preregistration. Use a focused topic, method, disease, or "
                    "research-area query derived from the note. Returns only "
                    "grants currently accepting applications that the user can "
                    "view. Returns at most five compact cards; call "
                    "get_grant_details for the full terms of one candidate."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Focused keywords describing the proposed research."
                            ),
                            "maxLength": _MAX_QUERY_CHARS,
                        }
                    },
                    "required": ["query"],
                },
                handler=self._search_grants,
            ),
            Tool(
                name=GET_GRANT_DETAILS,
                description=(
                    "Get the detailed description and RFP text for one grant "
                    "returned by search_grants. The same active/visible checks "
                    "are applied again."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "grant_id": {
                            "type": "integer",
                            "description": "Grant id from a search_grants card.",
                        }
                    },
                    "required": ["grant_id"],
                },
                handler=self._get_grant_details,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _search_grants(self, args: dict) -> dict:
        query = " ".join(str((args or {}).get("query") or "").split())
        if not query:
            return {"error": "query is required"}
        if len(query) > _MAX_QUERY_CHARS:
            return {"error": f"query exceeds {_MAX_QUERY_CHARS} characters"}

        try:
            grants = self._service.search(
                user=self._user, query=query, limit=_MAX_RESULTS
            )
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("grant search failed")
            return {"error": "grant search is temporarily unavailable"}

        return {
            "query": query,
            "grants": [self._serialize_card(grant) for grant in grants[:_MAX_RESULTS]],
        }

    @staticmethod
    def _base_fields(grant) -> tuple[dict, object | None]:
        posts = list(grant.unified_document.posts.all())
        post = posts[0] if posts else None
        title = (grant.short_title or "").strip()
        if not title and post is not None:
            title = (post.title or "").strip()
        url = None
        if post is not None and post.id and post.slug:
            url = f"{BASE_FRONTEND_URL}/grant/{post.id}/{post.slug}"
        return {
            "id": grant.id,
            "title": title,
            "organization": (grant.organization or "").strip(),
            "amount": str(grant.amount),
            "currency": grant.currency,
            "deadline": grant.end_date.isoformat() if grant.end_date else None,
            "url": url,
        }, post

    @classmethod
    def _serialize_card(cls, grant) -> dict:
        fields, post = cls._base_fields(grant)
        summary = (grant.description or "").strip()
        if not summary and post is not None:
            summary = (post.renderable_text or "").strip()
        fields["summary"] = summary[:_MAX_SUMMARY_CHARS]
        return fields

    @classmethod
    def _serialize_details(cls, grant) -> dict:
        fields, post = cls._base_fields(grant)
        fields.update(
            {
                "description": (grant.description or "").strip()[
                    :_MAX_DESCRIPTION_CHARS
                ],
                "post_content": (
                    (post.renderable_text or "").strip()[:_MAX_POST_CONTENT_CHARS]
                    if post is not None
                    else ""
                ),
                "application_visibility": grant.application_visibility,
            }
        )
        return fields

    def _get_grant_details(self, args: dict) -> dict:
        grant_id = (args or {}).get("grant_id")
        try:
            grant_id = int(grant_id)
        except (TypeError, ValueError):
            return {"error": "grant_id must be an integer"}
        try:
            grant = self._service.get_active_visible(user=self._user, grant_id=grant_id)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("grant detail lookup failed")
            return {"error": "grant details are temporarily unavailable"}
        if grant is None:
            return {"error": f"grant {grant_id} not found or not accessible"}
        return {"grant": self._serialize_details(grant)}
