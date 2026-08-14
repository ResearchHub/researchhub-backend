"""Grant discovery tools for the notebook chat agent."""

import logging

from purchase.services.grant_search_service import GrantSearchService
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.agent import Tool, Toolset

logger = logging.getLogger(__name__)

SEARCH_GRANTS = "search_grants"
_MAX_QUERY_CHARS = 500
_MAX_DESCRIPTION_CHARS = 3000
_MAX_POST_CONTENT_CHARS = 3000


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
                    "view, with their terms, deadlines, and ResearchHub URLs."
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
            )
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
            grants = self._service.search(user=self._user, query=query)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("grant search failed")
            return {"error": "grant search is temporarily unavailable"}

        return {
            "query": query,
            "grants": [self._serialize(grant) for grant in grants],
        }

    @staticmethod
    def _serialize(grant) -> dict:
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
            "description": (grant.description or "")[:_MAX_DESCRIPTION_CHARS],
            "post_content": (
                (post.renderable_text or "").strip()[:_MAX_POST_CONTENT_CHARS]
                if post is not None
                else ""
            ),
            "amount": str(grant.amount),
            "currency": grant.currency,
            "deadline": grant.end_date.isoformat() if grant.end_date else None,
            "application_visibility": grant.application_visibility,
            "url": url,
        }
