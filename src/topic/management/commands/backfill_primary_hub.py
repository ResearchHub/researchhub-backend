""" Single use script to backfill is_primary field in UnifiedDocumentTopics model"""

from django.core.management.base import BaseCommand

from topic.models import Topic, UnifiedDocumentTopics
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = "Backfill primary topic for OpenAlex topics in UnifiedDocumentTopics model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--id", default=None, type=int, help="Specific unified document id"
        )

    def handle(self, *args, **kwargs):
        id = kwargs["id"]

        distinct_unified_document_ids_list = []
        if id:
            distinct_unified_document_ids_list.append(id)
        else:
            distinct_unified_document_ids = UnifiedDocumentTopics.objects.values(
                "unified_document_id"
            ).distinct()
            distinct_unified_document_ids_list = list(
                distinct_unified_document_ids.values_list(
                    "unified_document_id", flat=True
                )
            )

        for unified_document_id in distinct_unified_document_ids_list:
            topics = UnifiedDocumentTopics.objects.filter(
                unified_document_id=unified_document_id
            )

            if topics.exists():
                print(f"Processing unified document id: {unified_document_id}")
                sorted_topics_by_score = sorted(
                    topics, key=lambda x: x.relevancy_score, reverse=True
                )

                topic_with_highest_score = sorted_topics_by_score[0]
                topic_with_highest_score.is_primary = True
                topic_with_highest_score.save()
