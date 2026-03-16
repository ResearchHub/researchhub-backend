from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch
from rest_framework.viewsets import ModelViewSet

from feed.models import FeedEntry
from feed.serializers import ActivityFeedEntrySerializer
from feed.views.common import FeedPagination
from feed.views.feed_view_mixin import FeedViewMixin
from purchase.models import Fundraise, UsdFundraiseContribution
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


class ActivityFeedViewSet(FeedViewMixin, ModelViewSet):
    """
    Feed of all activity (papers, posts, comments) on documents,
    without the main feed's preprint-hub filtering or personalization.

    Supports filtering by:
      - scope: "grants" returns all activity across every grant and
        every preregistration that applied to any grant.
        "peer_reviews" returns only peer review comments.
      - document_type: PREREGISTRATION, GRANT, etc.
      - grant_id: all activity on a grant and its applied preregistrations
      - content_type: RHCOMMENTMODEL, RESEARCHHUBPOST, PAPER, etc.

    Filters can be combined: e.g. ?scope=grants&content_type=RHCOMMENTMODEL
    returns only comments across all grant-related documents.
    """

    serializer_class = ActivityFeedEntrySerializer
    permission_classes = []
    pagination_class = FeedPagination
    http_method_names = ["get", "head", "options"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.add_user_votes_to_response(request.user, response.data)

        return response

    def get_queryset(self):
        queryset = (
            FeedEntry.objects.select_related(
                "content_type",
                "unified_document",
                "user",
                "user__author_profile",
                "user__userverification",
            )
            .prefetch_related(
                Prefetch(
                    "unified_document__fundraises",
                    queryset=Fundraise.objects.prefetch_related(
                        Prefetch(
                            "purchases",
                            queryset=Purchase.objects.select_related(
                                "user",
                                "user__author_profile",
                                "user__userverification",
                            ).order_by("-created_date"),
                            to_attr="prefetched_purchases",
                        ),
                        Prefetch(
                            "usd_contributions",
                            queryset=UsdFundraiseContribution.objects.select_related(
                                "user",
                                "user__author_profile",
                                "user__userverification",
                            )
                            .filter(is_refunded=False)
                            .order_by("-created_date"),
                            to_attr="prefetched_usd_contributions",
                        ),
                    ),
                    to_attr="prefetched_fundraises",
                ),
            )
            .order_by("-action_date")
        )

        scope = self.request.query_params.get("scope", "").lower()
        grant_id = self.request.query_params.get("grant_id")

        if grant_id:
            queryset = self._filter_by_grant(queryset, grant_id)
        elif scope == "grants":
            queryset = self._filter_all_grants(queryset)
        elif scope == "peer_reviews":
            queryset = self._filter_peer_reviews(queryset)
        else:
            document_type = self.request.query_params.get("document_type")
            if document_type:
                queryset = queryset.filter(
                    unified_document__document_type=(document_type.upper())
                )

        content_type = self.request.query_params.get("content_type")
        if content_type:
            queryset = self._filter_by_content_type(queryset, content_type)

        return queryset

    @staticmethod
    def _filter_by_grant(queryset, grant_id):
        """
        Return feed entries for a grant and all preregistrations
        that applied to it. This covers:
          - posts/comments on the grant document itself
          - posts/comments on preregistration documents applied
            to this grant (via GrantApplication)
        """
        try:
            grant = Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return queryset.none()

        ud_ids = {grant.unified_document_id}

        prereg_ud_ids = GrantApplication.objects.filter(
            grant=grant,
        ).values_list(
            "preregistration_post__unified_document_id",
            flat=True,
        )
        ud_ids.update(prereg_ud_ids)

        return queryset.filter(unified_document_id__in=ud_ids)

    @staticmethod
    def _filter_all_grants(queryset):
        """
        Return feed entries for every grant document and every
        preregistration that has applied to any grant.
        Excludes PENDING and DECLINED grants (moderation-only).
        """
        grant_ud_ids = Grant.objects.exclude(
            status__in=[Grant.PENDING, Grant.DECLINED]
        ).values_list("unified_document_id", flat=True)
        prereg_ud_ids = GrantApplication.objects.values_list(
            "preregistration_post__unified_document_id",
            flat=True,
        )
        all_ud_ids = set(grant_ud_ids) | set(prereg_ud_ids)
        return queryset.filter(unified_document_id__in=all_ud_ids)

    @staticmethod
    def _filter_peer_reviews(queryset):
        """
        Return feed entries for documents that have peer review comments.
        """
        comment_type = ContentType.objects.get_for_model(RhCommentModel)
        peer_review_ids = RhCommentModel.objects.filter(
            comment_type=PEER_REVIEW,
        ).values("id")

        document_ids = (
            FeedEntry.objects.filter(
                content_type=comment_type,
                object_id__in=peer_review_ids,
            )
            .values("unified_document_id")
            .distinct()
        )

        return queryset.filter(unified_document_id__in=document_ids)

    @staticmethod
    def _filter_by_content_type(queryset, content_type_name):
        """Filter feed entries by the model name of their content_type."""
        try:
            ct = ContentType.objects.get(model=content_type_name.lower())
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(content_type=ct)
