from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class Command(BaseCommand):
    help = "Populate the unified document ID field for all feed entries"

    def handle(self, *args, **kwargs):
        bounty_content_type = ContentType.objects.get_for_model(Bounty)
        paper_content_type = ContentType.objects.get_for_model(Paper)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        for feed_entry in FeedEntry.objects.filter(unified_document=1):
            if (
                feed_entry.content_type == bounty_content_type
                or feed_entry.content_type == comment_content_type
                or feed_entry.content_type == paper_content_type
                or feed_entry.content_type == post_content_type
            ):
                feed_entry.unified_document = feed_entry.item.unified_document
                feed_entry.save()
                print(
                    f"Feed entry={feed_entry.id} unified document ID={feed_entry.unified_document.id}"
                )
            else:
                print(
                    f"Feed entry={feed_entry.id} has unsupported content type {feed_entry.content_type}"
                )
