from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from search.analyzers import content_analyzer, title_analyzer
from utils import sentry

from .base import BaseDocument


@registry.register_document
class PostDocument(BaseDocument):
    auto_refresh = True
    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    hot_score = es_fields.IntegerField(attr="hot_score")
    score = es_fields.IntegerField(attr="score")
    discussion_count = es_fields.IntegerField(attr="discussion_count")
    unified_document_id = es_fields.IntegerField(attr="unified_document_id")
    created_date = es_fields.DateField(attr="created_date")
    updated_date = es_fields.DateField(attr="updated_date")
    preview_img = es_fields.TextField(attr="preview_img")
    renderable_text = es_fields.TextField(
        attr="renderable_text", analyzer=content_analyzer
    )
    created_by_id = es_fields.IntegerField(attr="created_by_id")
    authors = es_fields.ObjectField(
        attr="authors_indexing",
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    hubs = es_fields.ObjectField(
        attr="hubs_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.KeywordField(),
            "slug": es_fields.TextField(),
        },
    )
    suggestion_phrases = es_fields.Completion()
    title = es_fields.TextField(
        analyzer=title_analyzer,
    )
    slug = es_fields.TextField()

    class Index:
        name = "post"

    class Django:
        model = ResearchhubPost
        queryset_pagination = 250
        fields = [
            "id",
            "document_type",
        ]

    # Used specifically for "autocomplete" style suggest feature.
    # Inlcudes a bunch of phrases the user may search by.
    def prepare_suggestion_phrases(self, instance):
        phrases = []

        # Variation of title which may be searched by users
        if instance.title:
            phrases.append(instance.title)
            phrases.extend(instance.title.split())

        if instance.doi:
            phrases.append(instance.doi)

        # Variation of author names which may be searched by users
        try:
            author_names_only = [
                f"{author.first_name} {author.last_name}"
                for author in instance.unified_document.authors
                if author.first_name and author.last_name
            ]
            all_authors_as_str = ", ".join(author_names_only)
            created_by = (
                instance.created_by.first_name + " " + instance.created_by.last_name
            )

            phrases.append(all_authors_as_str)
            phrases.append(created_by)
            phrases.extend(author_names_only)
        except Exception as error:
            print(error)
            pass

        return {
            "input": list(set(phrases)),  # Dedupe using set
            "weight": 1,
        }

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
            return data
        except Exception as error:
            print("Post Indexing error: ", error, "Instance: ", instance.id)
            sentry.log_error(error)
            return False

    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False
