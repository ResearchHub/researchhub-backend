"""Permission-aware discovery of grants accepting applications."""

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.utils import timezone

from purchase.models import Grant
from researchhub_document.models import ResearchhubPost


class GrantSearchService:
    """Search active grants that are visible to the acting user."""

    @staticmethod
    def _active_visible(user):
        visible_document_ids = ResearchhubPost.objects.visible_to(user).values(
            "unified_document_id"
        )
        return Grant.objects.filter(
            status=Grant.OPEN,
            unified_document_id__in=visible_document_ids,
            unified_document__is_removed=False,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=timezone.now()))

    def search(self, *, user, query: str, limit: int = 5) -> list[Grant]:
        query = " ".join((query or "").split())
        if not query or limit <= 0:
            return []

        grant_fields = ("short_title", "organization", "description")
        post_fields = ("title", "renderable_text")

        # Match any useful keyword so a natural-language request does not have
        # to reproduce an RFP's wording exactly. Prefer whole-phrase matches,
        # then grants with the nearest deadline.
        grant_keyword_match = Q()
        post_keyword_match = Q()
        for keyword in query.split()[:12]:
            for field in grant_fields:
                grant_keyword_match |= Q(**{f"{field}__icontains": keyword})
            for field in post_fields:
                post_keyword_match |= Q(**{f"{field}__icontains": keyword})

        grant_phrase_match = Q()
        post_phrase_match = Q()
        for field in grant_fields:
            grant_phrase_match |= Q(**{f"{field}__icontains": query})
        for field in post_fields:
            post_phrase_match |= Q(**{f"{field}__icontains": query})

        posts = ResearchhubPost.objects.filter(
            unified_document_id=OuterRef("unified_document_id")
        )

        grants = (
            self._active_visible(user)
            .annotate(
                keyword_in_post=Exists(posts.filter(post_keyword_match)),
                phrase_in_post=Exists(posts.filter(post_phrase_match)),
            )
            .filter(grant_keyword_match | Q(keyword_in_post=True))
            .annotate(
                phrase_rank=Case(
                    When(
                        grant_phrase_match | Q(phrase_in_post=True),
                        then=Value(0),
                    ),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .select_related("unified_document")
            .prefetch_related("unified_document__posts")
            .order_by("phrase_rank", "end_date", "-created_date")
        )
        return list(grants[:limit])

    def get_active_visible(self, *, user, grant_id: int) -> Grant | None:
        """One application-ready grant, subject to the same visibility rules."""
        return (
            self._active_visible(user)
            .filter(id=grant_id)
            .select_related("unified_document")
            .prefetch_related("unified_document__posts")
            .first()
        )
