from django.conf import settings
from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce
from rest_framework import serializers

from discussion.serializers import VoteSerializer
from hub.models import Hub
from reputation.models import Bounty, BountySolution
from reputation.serializers.escrow_serializer import DynamicEscrowSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import DynamicUserSerializer
from utils import sentry
from utils.http import get_user_from_request


class SimpleHubSerializer(serializers.ModelSerializer):
    """Minimal hub serializer with just essential fields"""

    class Meta:
        model = Hub
        fields = ["id", "name", "slug"]


class BountySerializer(serializers.ModelSerializer):
    class Meta:
        model = Bounty
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class BountySolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BountySolution
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicBountySerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    escrow = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    solutions = serializers.SerializerMethodField()
    parent = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    subcategory = serializers.SerializerMethodField()
    journal = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()
    # Kobe: This is not great. This alias is used to disambiguate "parent" used in
    # contribution_views because simply using parent, may lead to infinite
    # recursive loop -_-
    bounty_parent = serializers.SerializerMethodField(method_name="get_parent")

    class Meta:
        model = Bounty
        fields = "__all__"

    def get_created_by(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_created_by", {})
        serializer = DynamicUserSerializer(
            bounty.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, bounty):
        content_type = bounty.item_content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_hubs(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_hubs", {})

        if _context_fields:
            include_fields = _context_fields.get("_include_fields", [])
            return list(bounty.unified_document.hubs.values(*include_fields))

        return []

    def get_category(self, bounty):
        """Return category hub if it exists"""
        if bounty.unified_document:
            category = bounty.unified_document.hubs.filter(
                namespace=Hub.Namespace.CATEGORY
            ).first()
            if category:
                return SimpleHubSerializer(category).data
        return None

    def get_subcategory(self, bounty):
        """Return subcategory hub if it exists"""
        if bounty.unified_document:
            subcategory = bounty.unified_document.hubs.filter(
                namespace=Hub.Namespace.SUBCATEGORY
            ).first()
            if subcategory:
                return SimpleHubSerializer(subcategory).data
        return None

    def get_journal(self, bounty):
        """Return journal hub if it exists"""
        if not bounty.unified_document:
            return None

        journal_hubs = [
            hub
            for hub in bounty.unified_document.hubs.all()
            if hub.namespace == Hub.Namespace.JOURNAL
        ]

        if not journal_hubs:
            return None

        researchhub_journal = None
        for hub in journal_hubs:
            if int(hub.id) == int(settings.RESEARCHHUB_JOURNAL_ID):
                researchhub_journal = hub
                break

        # Use ResearchHub Journal if found, otherwise use the first journal
        journal_hub = researchhub_journal or journal_hubs[0]

        if journal_hub:
            return {
                "id": journal_hub.id,
                "name": journal_hub.name,
                "slug": journal_hub.slug,
                "image": journal_hub.hub_image.url if journal_hub.hub_image else None,
            }
        return None

    def get_item(self, bounty):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_dbs_get_item", {})
        model_name = bounty.item_content_type.model
        object_id = bounty.item_object_id
        model_class = bounty.item_content_type.model_class()
        try:
            obj = model_class.objects.get(id=object_id)

            if model_name == "researchhubunifieddocument":
                serializer = DynamicUnifiedDocumentSerializer(
                    obj, context=context, **_context_fields
                )
            elif model_name == "rhcommentmodel":
                from researchhub_comment.serializers import DynamicRhCommentSerializer

                serializer = DynamicRhCommentSerializer(
                    obj, context=context, **_context_fields
                )

            if serializer is not None:
                return serializer.data
        except Exception as e:
            print(e)
            sentry.log_error(e)
            return None
        return None

    def get_escrow(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_escrow", {})
        serializer = DynamicEscrowSerializer(
            bounty.escrow, context=context, **_context_fields
        )
        return serializer.data

    def get_solutions(self, bounty):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_dbs_get_solutions", {})
        serializer = DynamicBountySolutionSerializer(
            bounty.solutions, context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_parent(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_parent", {})
        if parent := bounty.parent:
            serializer = DynamicBountySerializer(
                parent, context=context, **_context_fields
            )
            return serializer.data
        return None

    def get_unified_document(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            bounty.unified_document, context=context, **_context_fields
        )
        return serializer.data

    def get_total_amount(self, bounty):
        children_sum = bounty.children.aggregate(
            children_sum=Coalesce(
                Sum("amount"),
                0,
                output_field=DecimalField(),
            )
        )["children_sum"]
        return bounty.amount + children_sum

    def get_user_vote(self, bounty):
        vote = None
        user = get_user_from_request(self.context)
        try:
            if bounty.item_content_type.model == "rhcommentmodel":
                comment = bounty.item
                if user and not user.is_anonymous and comment:
                    vote = comment.votes.get(created_by=user)
                    vote = VoteSerializer(vote).data
                return vote
        except Exception:
            return None

    def get_metrics(self, bounty):
        """Return metrics for the bounty's unified document"""
        if bounty.unified_document:
            return {"votes": bounty.unified_document.score}
        return None


class DynamicBountySolutionSerializer(DynamicModelFieldSerializer):
    bounty = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = BountySolution
        fields = "__all__"

    def get_created_by(self, solution):
        context = self.context
        _context_fields = context.get("rep_dbss_get_created_by", {})
        serializer = DynamicUserSerializer(
            solution.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_bounty(self, solution):
        context = self.context
        _context_fields = context.get("rep_dbss_get_bounty", {})
        serializer = DynamicBountySerializer(
            solution.bounty, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, solution):
        content_type = solution.content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_item(self, solution):
        context = self.context
        _context_fields = context.get("rep_dbss_get_item", {})

        serializer = None
        solution_content_type = solution.content_type
        model_name = solution_content_type.model
        object_id = solution.object_id
        model_class = solution_content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "rhcommentmodel":
            from researchhub_comment.serializers import DynamicRhCommentSerializer

            serializer = DynamicRhCommentSerializer(
                obj, context=context, **_context_fields
            )
        if serializer is not None:
            return serializer.data
        return None
