import contextlib
import logging

import rest_framework.serializers as serializers
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import QueryDict

from discussion.models import Flag, Vote
from discussion.serializers import (
    DynamicFlagSerializer,
    DynamicVoteSerializer,
    GenericReactionSerializerMixin,
)
from feed.hot_score_utils import calculate_adjusted_score
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from paper.exceptions import PaperSerializerError
from paper.models import (
    Figure,
    Paper,
    PaperVersion,
)
from paper.related_models.authorship_model import Authorship
from paper.utils import (
    clean_abstract,
    pdf_copyright_allows_display,
)
from purchase.models import Purchase
from researchhub.serializers import (
    DynamicModelFieldSerializer,
    ModeratedDocumentStatusSerializerMixin,
)
from review.serializers.review_serializer import DynamicReviewSerializer
from user.models import Author
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils.http import get_user_from_request

logger = logging.getLogger(__name__)


class BasePaperSerializer(serializers.ModelSerializer, GenericReactionSerializerMixin):
    authors = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    pdf_copyright_allows_display = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.ReadOnlyField()
    unified_document = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(read_only=True)
    user_flag = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    version_list = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        exclude = ["references"]
        read_only_fields = [
            "user_vote",
            "user_flag",
            "unified_document_id",
            "slug",
        ]
        model = Paper

    def get_unified_document_id(self, instance):
        try:
            target_unified_doc = instance.unified_document
            return target_unified_doc.id if (target_unified_doc is not None) else None
        except Exception:
            return None

    # overriding innate django function
    def to_internal_value(self, data):
        data = self._transform_to_dict(data)
        data = self._copy_data(data)

        valid_authors = []
        for author_id in data.get("authors", []):
            if isinstance(author_id, Author):
                author_id = author_id.id
            if isinstance(author_id, dict):
                author_id = author_id.get("id", None)
            try:
                author = Author.objects.get(pk=author_id)
                valid_authors.append(author)
            except Author.DoesNotExist:
                logger.warning("Author with ID %s not found", author_id)
        data["authors"] = valid_authors

        return data

    def _transform_to_dict(self, obj):
        if isinstance(obj, QueryDict):
            authors = obj.getlist("authors", [])
            raw_authors = obj.getlist("raw_authors", [])
            obj = obj.dict()
            obj["authors"] = authors
            obj["raw_authors"] = raw_authors
        return obj

    def _copy_data(self, data):
        """Returns a copy of `data`.

        This is a helper method used to handle files which, when present in the
        data, prevent `.copy()` from working.

        Args:
            data (dict)
        """
        file = None
        with contextlib.suppress(KeyError):
            file = data.pop("file")

        data = data.copy()
        data["file"] = file
        return data

    def get_authors(self, paper):
        serializer = AuthorSerializer(
            paper.authors.filter(claimed=True),
            many=True,
            read_only=False,
            required=False,
            context=self.context,
        )
        return serializer.data

    def get_first_preview(self, paper):
        # If we don't show the PDFs on the paper page, we shouldn't have previews either
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )
        if (
            not self.get_pdf_copyright_allows_display(paper)
            and exclude_copyrighted_content
        ):
            return None

        try:
            figure = paper.figures.filter(figure_type=Figure.PREVIEW).first()
            if figure:
                return FigureSerializer(figure).data
        except AttributeError:
            return None

    def get_user_flag(self, paper):
        if self.context.get("purchase_minimal_serialization", False):
            return None

        flag = None
        user = get_user_from_request(self.context)
        if user:
            try:
                flag = paper.flags.get(created_by=user.id)
                flag = DynamicFlagSerializer(flag).data
            except Flag.DoesNotExist:
                pass
        return flag

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = paper.votes.get(created_by=user.id)
                vote = DynamicVoteSerializer(vote).data
            except Vote.DoesNotExist:
                pass
        return vote

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document,
            _include_fields=[
                "id",
                "reviews",
                "title",
                "documents",
                "paper_title",
                "slug",
                "is_removed",
                "document_type",
                "created_by",
            ],
            context={
                "doc_duds_get_created_by": {
                    "_include_fields": [
                        "id",
                        "author_profile",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
                "doc_duds_get_documents": {
                    "_include_fields": [
                        "id",
                        "title",
                        "slug",
                        "paper_title",
                    ]
                },
            },
            many=False,
        )

        return serializer.data

    def get_pdf_copyright_allows_display(self, paper):
        return pdf_copyright_allows_display(paper)

    def get_file(self, paper):
        file = paper.file
        if not file:
            return None

        # Don't return copyrighted content by default,
        # but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.file.url
        return None

    def get_pdf_url(self, paper):
        if not paper.pdf_url:
            return None

        # Don't return copyrighted content by default,
        # but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.pdf_url
        return None

    def get_version(self, paper):
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
            return paper_version.version
        except PaperVersion.DoesNotExist:
            return 1

    def get_version_list(self, paper) -> list:
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
        except PaperVersion.DoesNotExist:
            return [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                }
            ]

        paper_versions = (
            PaperVersion.objects.filter(
                original_paper_id=paper_version.original_paper_id
            )
            .select_related("paper")
            .order_by("version")
        )
        latest_version = paper_versions.last()

        # Return a list of version pointing to the paper_id
        return [
            {
                "version": version.version,
                "paper_id": version.paper.id,
                "publication_status": version.publication_status,
                "published_date": (
                    version.paper.paper_publish_date.strftime("%Y-%m-%d")
                    if version.paper.paper_publish_date
                    else None
                ),
                "message": version.message,
                "is_latest": version.version == latest_version.version,
                "is_version_of_record": (
                    version.version == latest_version.version
                    and version.publication_status == PaperVersion.PUBLISHED
                ),
            }
            for version in paper_versions
        ]

    def get_hubs(self, paper):
        if paper.unified_document:
            return SimpleHubSerializer(
                paper.unified_document.hubs.all(), many=True
            ).data
        return []


class PaperSerializer(BasePaperSerializer, ModeratedDocumentStatusSerializerMixin):
    authors = serializers.SerializerMethodField()
    uploaded_date = serializers.ReadOnlyField()

    class Meta:
        exclude = ["references"]
        read_only_fields = [
            "authors",
            "citations",
            "discussion_count",
            "external_source",
            "id",
            "is_open_access",
            "is_removed",
            "pdf_license_url",
            "retrieved_from_external_source",
            "score",
            "slug",
            "unified_document_id",
            "unified_document",
            "user_flag",
            "user_vote",
            "version",
            "version_list",
        ]
        moderator_only_update_fields = [
            "pdf_license",
        ]

        patch_read_only_fields = ["uploaded_by"]
        model = Paper

    def update(self, instance, validated_data):
        request = self.context.get("request", None)

        # Check permissions
        if not request.user.moderator:
            for field in self.Meta.moderator_only_update_fields:
                if field in validated_data:
                    validated_data.pop(field, None)

        validated_data.pop("authors", [None])
        # Discard any `file` key so it cannot reach the FileField
        # (`to_internal_value` skips DRF validation).
        validated_data.pop("file", None)
        hubs = validated_data.pop("hubs", None)
        pdf_license = validated_data.get("pdf_license", None)
        validated_data.pop("raw_authors", [])

        try:
            with transaction.atomic():
                # Temporary fix for updating read only fields
                read_only_fields = (
                    self.Meta.read_only_fields + self.Meta.patch_read_only_fields
                )
                for read_only_field in read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)
                self._clean_abstract(validated_data)

                paper = super().update(instance, validated_data)
                paper.full_clean(exclude=["paper_type"])

                unified_doc = paper.unified_document
                if hubs is not None:
                    # Create list of hub IDs independent of whether hubs is
                    # a list of Hub objects or a list of hub IDs.
                    new_hub_ids = [h.id if hasattr(h, "id") else int(h) for h in hubs]

                    # Get the current hub IDs from the unified document
                    current_hub_ids = list(
                        unified_doc.hubs.values_list("id", flat=True)
                    )

                    # Calculate the actual delta
                    remove_ids = [
                        hid for hid in current_hub_ids if hid not in new_hub_ids
                    ]
                    add_ids = [hid for hid in new_hub_ids if hid not in current_hub_ids]

                    if remove_ids:
                        unified_doc.hubs.remove(*remove_ids)
                    if add_ids:
                        unified_doc.hubs.add(*add_ids)

                if pdf_license:
                    paper.pdf_license = pdf_license
                    paper.save(update_fields=["pdf_license"])

                return paper
        except Exception as e:
            error = PaperSerializerError(e, "Failed to update paper")
            logger.exception("Failed to update paper")
            raise error

    def _clean_abstract(self, data):
        abstract = data.get("abstract")
        if abstract:
            cleaned_text = clean_abstract(abstract)
            data.update(abstract=cleaned_text)

    def get_authors(self, paper):
        serializer = AuthorSerializer(
            paper.authors.all(),
            many=True,
            read_only=False,
            required=False,
            context=self.context,
        )
        return serializer.data

    def get_discussion(self, paper):
        return None

    def get_file(self, paper):
        external_source = paper.external_source
        file = paper.file
        if external_source and external_source.lower() == "arxiv":
            pdf_url = paper.pdf_url
            url = paper.url
            if pdf_url:
                return pdf_url
            elif url:
                return url
            return None
        elif file:
            return file.url
        return None


class AuthorshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Authorship
        fields = "__all__"


class DynamicAuthorshipSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = "__all__"
        model = Authorship

    def to_representation(self, authorship):
        context = self.context
        context_fields = {
            "_include_fields": [
                "id",
                "first_name",
                "last_name",
                "user",
            ]
        }
        author_data = DynamicAuthorSerializer(
            authorship.author,
            context=context,
            **context_fields,
        ).data

        authorship_data = {
            "position": authorship.author_position,
            "is_corresponding": authorship.is_corresponding,
        }

        # Nest authorship details within author data
        return {**author_data, "authorship": authorship_data}


class DynamicPaperSerializer(
    DynamicModelFieldSerializer,
    GenericReactionSerializerMixin,
    ModeratedDocumentStatusSerializerMixin,
):
    authors = serializers.SerializerMethodField()
    bounties = serializers.SerializerMethodField()
    discussions = serializers.SerializerMethodField()
    discussion_aggregates = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    adjusted_score = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    pdf_copyright_allows_display = serializers.SerializerMethodField()
    peer_reviews = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    version_list = serializers.SerializerMethodField()

    class Meta:
        model = Paper
        fields = "__all__"

    def get_authors(self, paper):

        context = self.context
        _context_fields = context.get("pap_dps_get_authorships", {})

        authorships = (
            paper.authorships.annotate(
                author_position_order=Case(
                    When(author_position="first", then=Value(1)),
                    When(author_position="middle", then=Value(2)),
                    When(author_position="last", then=Value(3)),
                    output_field=IntegerField(),
                )
            )
            .select_related("author")
            .all()
            .order_by("author_position_order")
        )

        serializer = DynamicAuthorshipSerializer(
            authorships, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        context = self.context
        _context_fields = context.get("pap_dps_get_user_vote", {})
        if user:
            try:
                vote = paper.votes.get(created_by=user.id)
                vote = DynamicVoteSerializer(
                    vote,
                    context=self.context,
                    **_context_fields,
                ).data

            except Vote.DoesNotExist:
                pass

        return vote

    def get_peer_reviews(self, paper):
        from review.models import Review

        context = self.context
        _context_fields = context.get("pap_dps_get_peer_reviews", {})
        unified_document = paper.unified_document
        if not unified_document:
            return []

        reviews = Review.objects.filter(
            unified_document=unified_document,
            is_removed=False,
        )
        serializer = DynamicReviewSerializer(
            reviews,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_bounties(self, paper):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_bounties", {})
        _select_related_fields = context.get("pap_dps_get_bounties_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_bounties_prefetch", [])
        bounties = (
            paper.unified_document.related_bounties.select_related(
                *_select_related_fields
            )
            .prefetch_related(*_prefetch_related_fields)
            .all()
        )
        serializer = DynamicBountySerializer(
            bounties,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussions(self, paper):
        from django.contrib.contenttypes.models import ContentType

        from paper.services.paper_version_service import PaperService
        from researchhub_comment.serializers import DynamicRhThreadSerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_discussions", {})
        _select_related_fields = context.get("pap_dps_get_discussions_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_discussions_prefetch", [])

        # Get paper service from context or create default instance
        paper_service = context.get("paper_service", PaperService())

        # Get all versions of this paper
        paper_versions = paper_service.get_all_paper_versions(paper.id)

        # Get content type for Paper model
        paper_content_type = ContentType.objects.get_for_model(paper)

        # Get threads for all paper versions
        from researchhub_comment.models import RhCommentThreadModel

        thread_queryset = (
            RhCommentThreadModel.objects.filter(
                content_type=paper_content_type,
                object_id__in=paper_versions.values_list("id", flat=True),
            )
            .select_related(*_select_related_fields)
            .prefetch_related(*_prefetch_related_fields)
        )

        serializer = DynamicRhThreadSerializer(
            thread_queryset,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussion_aggregates(self, paper):
        from django.contrib.contenttypes.models import ContentType

        from paper.services.paper_version_service import PaperService
        from researchhub_comment.models import RhCommentThreadModel

        # Get paper service from context or create default instance
        paper_service = self.context.get("paper_service", PaperService())

        # Get all versions of this paper
        paper_versions = paper_service.get_all_paper_versions(paper.id)

        # Get content type for Paper model
        paper_content_type = ContentType.objects.get_for_model(paper)

        # Get threads for all paper versions
        thread_queryset = RhCommentThreadModel.objects.filter(
            content_type=paper_content_type,
            object_id__in=paper_versions.values_list("id", flat=True),
        )

        return thread_queryset.get_discussion_aggregates(paper)

    def get_hubs(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_hubs", {})

        serializer = DynamicHubSerializer(
            paper.unified_document.hubs,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_first_preview(self, paper):
        context = self.context

        # If we don't show the PDFs on the paper page, we shouldn't have previews either
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )
        if (
            not self.get_pdf_copyright_allows_display(paper)
            and exclude_copyrighted_content
        ):
            return None

        _context_fields = context.get("pap_dps_get_first_preview", {})

        # Priority: is_primary > preview figures > first figure
        primary_figure = paper.figures.filter(is_primary=True).first()
        if primary_figure:
            serializer = DynamicFigureSerializer(
                primary_figure, context=context, **_context_fields
            )
            return serializer.data

        preview_figure = paper.figures.filter(figure_type=Figure.PREVIEW).first()
        if preview_figure:
            serializer = DynamicFigureSerializer(
                preview_figure, context=context, **_context_fields
            )
            return serializer.data

        if paper.figures.exists():
            # Using prefetches to filter by figure preview
            # Slicing with [0] because .first() does not use prefetch cache
            serializer = DynamicFigureSerializer(
                paper.figures.all()[0], context=context, **_context_fields
            )
            return serializer.data
        return None

    def get_purchases(self, paper):
        from purchase.serializers import DynamicPurchaseSerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_purchases", {})
        _select_related_fields = context.get("pap_dps_get_purchases_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_purchases_prefetch", [])
        serializer = DynamicPurchaseSerializer(
            paper.purchases.filter(purchase_type=Purchase.BOOST)
            .select_related(*_select_related_fields)
            .prefetch_related(*_prefetch_related_fields),
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_score(self, paper):
        return paper.calculate_score()

    def get_adjusted_score(self, paper):
        """
        Calculate adjusted score on-the-fly from paper data.
        """
        base_votes = paper.calculate_score()

        # Get external metrics from paper.external_metadata
        external_metrics = {}
        if paper.external_metadata:
            external_metrics = paper.external_metadata.get("metrics", {})

        return calculate_adjusted_score(base_votes, external_metrics)

    def get_unified_document(self, paper):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        # NOTE: calvinhlee - dynamic handling is very confusing. This has to be better.
        context = self.context
        _context_fields = context.get(
            "pap_dps_get_unified_document", {"_exclude_fields": ["documents"]}
        )

        serializer = DynamicUnifiedDocumentSerializer(
            paper.unified_document,
            context=context,
            **_context_fields,
        )

        return serializer.data

    def get_unified_document_id(self, paper):
        try:
            target_unified_doc = paper.unified_document
            return target_unified_doc.id if (target_unified_doc is not None) else None
        except Exception:
            return None

    def get_uploaded_by(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_uploaded_by", {})
        uploaded_by = paper.uploaded_by

        if not uploaded_by:
            return None

        serializer = DynamicUserSerializer(
            uploaded_by, context=context, **_context_fields
        )
        return serializer.data

    def get_pdf_copyright_allows_display(self, paper):
        return pdf_copyright_allows_display(paper)

    def get_file(self, paper):
        if not paper.file:
            return None

        # Don't return copyrighted content by default,
        # but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.file.url
        return None

    def get_pdf_url(self, paper):
        if not paper.pdf_url:
            return None

        # Don't return copyrighted content by default,
        # but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.pdf_url
        return None

    def get_version(self, paper):
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
            return paper_version.version
        except PaperVersion.DoesNotExist:
            return 1

    def get_version_list(self, paper) -> list:
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
        except PaperVersion.DoesNotExist:
            return [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                }
            ]

        paper_versions = (
            PaperVersion.objects.filter(
                original_paper_id=paper_version.original_paper_id
            )
            .select_related("paper")
            .order_by("version")
        )
        latest_version = paper_versions.last()

        # Return a list of version pointing to the paper_id
        return [
            {
                "version": version.version,
                "paper_id": version.paper.id,
                "publication_status": version.publication_status,
                "published_date": (
                    version.paper.paper_publish_date.strftime("%Y-%m-%d")
                    if version.paper.paper_publish_date
                    else None
                ),
                "message": version.message,
                "is_latest": version.version == latest_version.version,
                "is_version_of_record": (
                    version.version == latest_version.version
                    and version.publication_status == PaperVersion.PUBLISHED
                ),
            }
            for version in paper_versions
        ]


class FigureSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        model = Figure

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        if user.is_anonymous:
            user = None
        validated_data["created_by"] = user
        figure = super().create(validated_data)
        return figure


class DynamicFigureSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = "__all__"
        model = Figure
