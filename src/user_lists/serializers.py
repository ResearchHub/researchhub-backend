from django.db.models import Count, Q

from hub.models import Hub
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)
from rest_framework import serializers
from topic.models import Topic
from user.related_models.author_model import Author
from utils.serializers import DefaultAuthenticatedSerializer

from .models import List, ListItem


def _get_top_items(obj, model, doc_path, values_fields):
    filter_kwargs = {
        f"{doc_path}__user_list_items__parent_list": obj,
        f"{doc_path}__user_list_items__is_removed": False,
        f"{doc_path}__is_removed": False,
    }
    q_filter = Q(**{f"{doc_path}__user_list_items__parent_list": obj}) & Q(
        **{f"{doc_path}__user_list_items__is_removed": False}
    )
    return list(
        model.objects.filter(**filter_kwargs)
        .annotate(count=Count(f"{doc_path}__user_list_items", filter=q_filter, distinct=True))
        .order_by("-count")[:5]
        .values(*values_fields)
    )


def _get_doc_ids_by_type(doc_ids, document_type=None):
    queryset = ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
    if document_type:
        queryset = queryset.filter(document_type=document_type)
    else:
        queryset = queryset.exclude(document_type=PAPER)
    return list(queryset.values_list("id", flat=True))


def _get_author_ids_from_queryset(queryset):
    return queryset.values_list("id", flat=True).distinct()


class ListSerializer(DefaultAuthenticatedSerializer):
    top_authors = serializers.SerializerMethodField()
    top_hubs = serializers.SerializerMethodField()
    top_topics = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = [
            "id",
            "name",
            "is_public",
            "created_date",
            "updated_date",
            "created_by",
            "top_authors",
            "top_hubs",
            "top_topics",
            "items_count",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by"]

    def get_items_count(self, obj):
        return obj.items.filter(is_removed=False).count()

    def _get_list_doc_ids(self, obj):
        return list(obj.items.filter(is_removed=False).values_list("unified_document_id", flat=True).distinct())

    def _get_author_doc_count(self, author, paper_doc_ids, post_doc_ids, post_ids):
        doc_ids_set = set()
        if paper_doc_ids:
            doc_ids_set.update(
                author.authorships.filter(paper__unified_document_id__in=paper_doc_ids)
                .values_list("paper__unified_document_id", flat=True)
                .distinct()
            )
        if post_doc_ids and post_ids:
            doc_ids_set.update(
                author.authored_posts.filter(id__in=post_ids, unified_document_id__in=post_doc_ids)
                .values_list("unified_document_id", flat=True)
                .distinct()
            )
            if getattr(author, "user", None):
                try:
                    doc_ids_set.update(
                        author.user.created_posts.filter(id__in=post_ids, unified_document_id__in=post_doc_ids)
                        .values_list("unified_document_id", flat=True)
                        .distinct()
                    )
                except Exception:
                    pass
        return len(doc_ids_set)

    def _build_author_dict(self, author_id, author, count):
        return {
            "id": author_id,
            "first_name": author.first_name,
            "last_name": author.last_name,
            "full_name": f"{author.first_name} {author.last_name}",
            "count": count,
        }

    def get_top_authors(self, obj):
        doc_ids = self._get_list_doc_ids(obj)
        if not doc_ids:
            return []

        paper_doc_ids = _get_doc_ids_by_type(doc_ids, PAPER)
        post_doc_ids = _get_doc_ids_by_type(doc_ids)

        author_ids = set()
        post_ids = []
        if paper_doc_ids:
            author_ids.update(_get_author_ids_from_queryset(Author.objects.filter(authorships__paper__unified_document_id__in=paper_doc_ids)))
        if post_doc_ids:
            post_ids = list(ResearchhubPost.objects.filter(unified_document_id__in=post_doc_ids).values_list("id", flat=True))
            if post_ids:
                author_ids.update(_get_author_ids_from_queryset(Author.objects.filter(authored_posts__id__in=post_ids)))
                author_ids.update(_get_author_ids_from_queryset(Author.objects.filter(user__created_posts__id__in=post_ids)))

        if not author_ids:
            return []

        author_counts = {}
        for author_id in author_ids:
            try:
                author = Author.objects.get(id=author_id)
                count = self._get_author_doc_count(author, paper_doc_ids, post_doc_ids, post_ids)
                if count > 0:
                    author_counts[author_id] = self._build_author_dict(author_id, author, count)
            except (Author.DoesNotExist, Exception):
                continue

        return sorted(author_counts.values(), key=lambda x: x["count"], reverse=True)[:5]

    def get_top_hubs(self, obj):
        return _get_top_items(obj, Hub, "related_documents", ["id", "name", "slug"])

    def get_top_topics(self, obj):
        return _get_top_items(obj, Topic, "documents", ["id", "display_name"])


class ListItemSerializer(DefaultAuthenticatedSerializer):
    unified_document = serializers.PrimaryKeyRelatedField(
        queryset=ResearchhubUnifiedDocument.objects.filter(is_removed=False), required=True
    )

    class Meta:
        model = ListItem
        fields = ["id", "parent_list", "unified_document", "created_date", "created_by"]
        read_only_fields = ["id", "created_date", "created_by"]


_UNIFIED_DOC_CONTEXT = {
    "doc_duds_get_documents": {
        "_include_fields": [
            "id",
            "created_date",
            "title",
            "slug",
            "authors",
            "abstract",
            "doi",
            "image_url",
            "renderable_text",
            "document_type",
            "score",
            "discussion_count",
            "hubs",
            "created_by",
            "unified_document",
            "unified_document_id",
            "fundraise",
            "grant",
        ]
    },
    "doc_duds_get_hubs": {"_include_fields": ["id", "name", "slug"]},
    "doc_duds_get_created_by": {"_include_fields": ["id", "author_profile", "first_name", "last_name"]},
    "doc_duds_get_fundraise": {
        "_include_fields": [
            "id",
            "status",
            "goal_amount",
            "goal_currency",
            "start_date",
            "end_date",
            "amount_raised",
            "contributors",
            "created_by",
        ]
    },
    "doc_duds_get_grant": {
        "_include_fields": [
            "id",
            "status",
            "amount",
            "currency",
            "organization",
            "description",
            "start_date",
            "end_date",
            "created_by",
            "contacts",
            "applications",
        ]
    },
    "pap_dps_get_authors": {"_include_fields": ["id", "first_name", "last_name", "author_profile"]},
    "pap_dps_get_unified_document": {"_include_fields": ["id", "fundraise", "grant"]},
    "doc_dps_get_authors": {"_include_fields": ["id", "first_name", "last_name", "author_profile"]},
    "doc_dps_get_unified_document": {"_include_fields": ["id", "fundraise", "grant"]},
    "pch_dfs_get_contributors": {"_include_fields": ["id", "author_profile", "first_name", "last_name", "profile_image"]},
    "pch_dfs_get_created_by": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
    "pch_dgs_get_created_by": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
    "pch_dgs_get_contacts": {"_include_fields": ["id", "first_name", "last_name", "profile_image", "author_profile"]},
}


class ListItemDetailSerializer(ListItemSerializer):
    unified_document_data = serializers.SerializerMethodField()

    class Meta(ListItemSerializer.Meta):
        fields = ListItemSerializer.Meta.fields + ["unified_document_data"]

    def get_unified_document_data(self, obj):
        context = {**self.context, **_UNIFIED_DOC_CONTEXT}
        try:
            return DynamicUnifiedDocumentSerializer(
                obj.unified_document,
                _include_fields=[
                    "id",
                    "created_date",
                    "title",
                    "slug",
                    "is_removed",
                    "document_type",
                    "hubs",
                    "created_by",
                    "documents",
                    "score",
                    "hot_score",
                    "reviews",
                    "fundraise",
                    "grant",
                ],
                context=context,
            ).data
        except Exception:
            return {
                "id": obj.unified_document.id,
                "document_type": obj.unified_document.document_type,
                "is_removed": obj.unified_document.is_removed,
            }


class ListDetailSerializer(ListSerializer):
    items = serializers.SerializerMethodField()

    class Meta(ListSerializer.Meta):
        fields = ListSerializer.Meta.fields + ["items"]

    def get_items(self, obj):
        # Return first page (20 items) for the retrieve endpoint
        # For full pagination, use GET /user_list_item/?parent_list=<id>
        from feed.views.common import FeedPagination
        paginator = FeedPagination()
        items_queryset = obj.items.filter(is_removed=False).order_by("-created_date")
        paginated_items = list(items_queryset[:paginator.page_size])
        return ListItemDetailSerializer(paginated_items, many=True, context=self.context).data
