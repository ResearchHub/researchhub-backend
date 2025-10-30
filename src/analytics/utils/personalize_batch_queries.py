from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.utils import timezone

from purchase.models import GrantApplication, Purchase
from reputation.models import BountySolution
from researchhub_document.models import ResearchhubUnifiedDocument


class PersonalizeBatchQueries:
    """Executes batch queries for Personalize item auxiliary data."""

    def fetch_all(self, doc_ids: list[int]) -> dict:
        """Fetch all auxiliary data for a batch of document IDs."""
        return {
            "bounty": self.fetch_bounty_data(doc_ids),
            "proposal": self.fetch_proposal_data(doc_ids),
            "rfp": self.fetch_rfp_data(doc_ids),
            "review_count": self.fetch_review_count_data(doc_ids),
        }

    def fetch_bounty_data(self, doc_ids: list[int]) -> dict[int, dict]:
        """Fetch bounty flags for document IDs."""

        bounty_map = defaultdict(
            lambda: {"has_active_bounty": False, "has_solutions": False}
        )

        open_bounties = (
            ResearchhubUnifiedDocument.objects.filter(
                id__in=doc_ids, related_bounties__status="OPEN"
            )
            .values_list("id", flat=True)
            .distinct()
        )

        for doc_id in open_bounties:
            bounty_map[doc_id]["has_active_bounty"] = True

        bounty_ids_with_solutions = (
            BountySolution.objects.filter(bounty__unified_document_id__in=doc_ids)
            .values_list("bounty__unified_document_id", flat=True)
            .distinct()
        )

        for doc_id in bounty_ids_with_solutions:
            bounty_map[doc_id]["has_solutions"] = True

        return dict(bounty_map)

    def fetch_proposal_data(self, doc_ids: list[int]) -> dict[int, dict]:
        """Fetch proposal/fundraise flags for document IDs."""
        from purchase.models import Fundraise

        proposal_map = defaultdict(lambda: {"is_open": False, "has_funders": False})

        open_fundraises = (
            ResearchhubUnifiedDocument.objects.filter(
                id__in=doc_ids,
                document_type="PREREGISTRATION",
                fundraises__status="OPEN",
            )
            .filter(
                Q(fundraises__end_date__isnull=True)
                | Q(fundraises__end_date__gte=timezone.now())
            )
            .values_list("id", flat=True)
            .distinct()
        )

        for doc_id in open_fundraises:
            proposal_map[doc_id]["is_open"] = True

        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        fundraise_ids_with_funders = (
            Purchase.objects.filter(
                content_type=fundraise_content_type,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            )
            .values_list("object_id", flat=True)
            .distinct()
        )

        docs_with_funders = (
            ResearchhubUnifiedDocument.objects.filter(
                id__in=doc_ids,
                document_type="PREREGISTRATION",
                fundraises__id__in=fundraise_ids_with_funders,
            )
            .values_list("id", flat=True)
            .distinct()
        )

        for doc_id in docs_with_funders:
            proposal_map[doc_id]["has_funders"] = True

        return dict(proposal_map)

    def fetch_rfp_data(self, doc_ids: list[int]) -> dict[int, dict]:
        """Fetch RFP/grant flags for document IDs."""
        rfp_map = defaultdict(lambda: {"is_open": False, "has_applicants": False})

        open_grants = (
            ResearchhubUnifiedDocument.objects.filter(
                id__in=doc_ids, document_type="GRANT", grants__status="OPEN"
            )
            .filter(
                Q(grants__end_date__isnull=True)
                | Q(grants__end_date__gte=timezone.now())
            )
            .values_list("id", flat=True)
            .distinct()
        )

        for doc_id in open_grants:
            rfp_map[doc_id]["is_open"] = True

        grant_ids_with_applicants = (
            GrantApplication.objects.filter(grant__unified_document_id__in=doc_ids)
            .values_list("grant__unified_document_id", flat=True)
            .distinct()
        )

        for doc_id in grant_ids_with_applicants:
            rfp_map[doc_id]["has_applicants"] = True

        return dict(rfp_map)

    def fetch_review_count_data(self, doc_ids: list[int]) -> dict[int, int]:
        """Fetch peer review counts for document IDs."""
        review_counts = (
            ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
            .annotate(
                review_count=Count("reviews", filter=Q(reviews__is_removed=False))
            )
            .values("id", "review_count")
        )

        return {item["id"]: item["review_count"] for item in review_counts}
