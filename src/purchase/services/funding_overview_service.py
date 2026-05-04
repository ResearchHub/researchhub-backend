"""Services for funding and grant overview dashboard metrics."""

from institution.models import Institution
from institution.serializers import DynamicInstitutionSerializer
from purchase.models import Grant, GrantApplication
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.services.overview_mixin import OverviewMixin
from purchase.utils import get_funded_fundraise_ids
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User
from user.related_models.author_institution import AuthorInstitution


class FundingOverviewService(OverviewMixin):
    """Funding portfolio dashboard metrics for grant creators."""

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""
        grant_fundraise_ids = self._grant_fundraise_ids(user)
        all_funded_ids = list(get_funded_fundraise_ids(user.id))

        return {
            "matched_funds": self._matched_contributions_breakdown(
                user.id, grant_fundraise_ids
            ),
            "distributed_funds": self._user_contributions_breakdown(
                user.id, all_funded_ids
            ),
            "supported_proposals": self._supported_proposals(all_funded_ids),
            "supported_institutions": self._supported_institutions_serialized(
                all_funded_ids
            ),
        }

    def _grant_fundraise_ids(self, user: User) -> list[int]:
        """Fundraise IDs for proposals that applied to this user's grants."""
        return list(
            GrantApplication.objects.for_user_grants(user)
            .exclude(
                preregistration_post__unified_document__fundraises__id__isnull=True
            )
            .values_list(
                "preregistration_post__unified_document__fundraises__id",
                flat=True,
            )
            .distinct()
        )

    def _supported_proposals(self, funded_fundraise_ids: list[int]) -> list[dict]:
        """Proposals (preregistration posts) the funder contributed to."""
        if not funded_fundraise_ids:
            return []

        posts = (
            ResearchhubPost.objects.filter(
                unified_document__fundraises__id__in=funded_fundraise_ids,
            )
            .select_related("unified_document", "created_by__author_profile")
            .distinct()
        )

        return [self._serialize_proposal(post) for post in posts]

    @staticmethod
    def _supported_institutions_serialized(funded_fundraise_ids: list[int]) -> list:
        """Distinct institutions for supported proposal creators."""
        if not funded_fundraise_ids:
            return []

        author_ids = (
            ResearchhubPost.objects.filter(
                unified_document__fundraises__id__in=funded_fundraise_ids,
                created_by__author_profile__isnull=False,
            )
            .values_list("created_by__author_profile__id", flat=True)
            .distinct()
        )
        institution_ids = (
            AuthorInstitution.objects.filter(author_id__in=author_ids)
            .values_list("institution_id", flat=True)
            .distinct()
        )
        institutions = Institution.objects.filter(id__in=institution_ids).order_by(
            "display_name",
            "id",
        )

        return DynamicInstitutionSerializer(
            institutions,
            many=True,
            _exclude_fields=["institutions"],
        ).data

    def _serialize_proposal(self, post: ResearchhubPost) -> dict:
        creator = post.created_by
        author = getattr(creator, "author_profile", None) if creator else None

        return {
            "unified_document": {
                "id": post.unified_document_id,
                "title": post.title,
                "slug": post.slug,
            },
            "id": post.id,
            "created_by": (
                {
                    "id": creator.id,
                    "author_profile": self._serialize_author_profile(author),
                }
                if creator
                else None
            ),
        }

    @staticmethod
    def _serialize_author_profile(author) -> dict:
        if not author:
            return {"id": None, "first_name": "", "last_name": "", "profile_image": ""}

        profile_image = ""
        if author.profile_image:
            try:
                profile_image = author.profile_image.url
            except ValueError:
                profile_image = str(author.profile_image)

        return {
            "id": author.id,
            "first_name": author.first_name,
            "last_name": author.last_name,
            "profile_image": profile_image,
        }


class GrantOverviewService(OverviewMixin):
    """Service for calculating grant-specific dashboard metrics."""

    def get_grant_overview(self, user: User, grant: Grant) -> dict:
        """Return metrics for a specific grant."""
        applications = GrantApplication.objects.filter(grant=grant)
        fundraise_ids = list(
            applications.exclude(
                preregistration_post__unified_document__fundraises__id__isnull=True
            )
            .values_list(
                "preregistration_post__unified_document__fundraises__id", flat=True
            )
            .distinct()
        )
        user_funded_ids = get_funded_fundraise_ids(user.id)
        funded_fundraise_ids = list(set(fundraise_ids) & user_funded_ids)

        exchange_rate = RscExchangeRate.get_latest()

        return {
            "budget_used_usd": round(
                self._user_contributions_usd(user.id, fundraise_ids, exchange_rate), 2
            ),
            "budget_total_usd": float(grant.amount),
            "matched_funding_usd": round(
                self._matched_contributions_usd(
                    user.id, funded_fundraise_ids, exchange_rate
                ),
                2,
            ),
            "total_proposals": applications.count(),
            "proposals_funded": len(funded_fundraise_ids),
        }
