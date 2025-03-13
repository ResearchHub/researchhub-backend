import csv
import os

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from discussion.reaction_models import Vote
from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User


class Command(BaseCommand):
    help = "Export data for Amazon Personalize"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            default="personalize_data",
            help="Directory to save the exported data files",
        )

    def handle(self, *args, **options):
        output_dir = options["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        self.stdout.write(self.style.SUCCESS(f"Exporting data to {output_dir}"))

        # Export users
        self.export_users(output_dir)

        # Export items (unified documents)
        self.export_items(output_dir)

        # Export interactions
        self.export_interactions(output_dir)

        self.stdout.write(self.style.SUCCESS("Data export completed successfully"))

    def export_users(self, output_dir):
        """Export user data for Amazon Personalize."""
        self.stdout.write("Exporting users...")

        users = User.objects.filter(is_active=True)

        with open(os.path.join(output_dir, "users.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["USER_ID"])

            for user in users:
                writer.writerow([user.id])

        self.stdout.write(self.style.SUCCESS(f"Exported {users.count()} users"))

    def export_items(self, output_dir):
        """Export item data (unified documents) for Amazon Personalize."""
        self.stdout.write("Exporting items (unified documents)...")

        items = ResearchhubUnifiedDocument.objects.filter(is_removed=False)

        with open(os.path.join(output_dir, "items.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["ITEM_ID", "CREATION_TIMESTAMP", "DOCUMENT_TYPE", "HUB_IDS"]
            )

            for item in items:
                # Get document type
                if hasattr(item, "paper") and item.paper:
                    doc_type = "PAPER"
                elif hasattr(item, "post") and item.post:
                    doc_type = "POST"
                else:
                    doc_type = "OTHER"

                # Get hub IDs
                hub_ids = ",".join([str(hub.id) for hub in item.hubs.all()])

                # Format timestamp for Amazon Personalize
                timestamp = int(item.created_date.timestamp())

                writer.writerow([item.id, timestamp, doc_type, hub_ids])

        self.stdout.write(self.style.SUCCESS(f"Exported {items.count()} items"))

    def export_interactions(self, output_dir):
        """Export user-item interactions for Amazon Personalize."""
        self.stdout.write("Exporting interactions...")

        # Get content types
        paper_content_type = ContentType.objects.get_for_model(Paper)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Export view interactions from feed entries
        with open(os.path.join(output_dir, "interactions.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["USER_ID", "ITEM_ID", "TIMESTAMP", "EVENT_TYPE", "EVENT_VALUE"]
            )

            # Process view interactions (from feed entries)
            self.stdout.write("Processing view interactions...")
            feed_entries = FeedEntry.objects.filter(
                user__isnull=False, unified_document__isnull=False
            ).select_related("user", "unified_document")

            for entry in feed_entries:
                timestamp = int(entry.action_date.timestamp())
                writer.writerow(
                    [entry.user_id, entry.unified_document_id, timestamp, "VIEW", 1]
                )

            # Process vote interactions
            self.stdout.write("Processing vote interactions...")
            votes = Vote.objects.filter(
                user__isnull=False,
                content_type__in=[paper_content_type, post_content_type],
            ).select_related("user", "content_type")

            for vote in votes:
                # Get the unified document ID
                unified_doc_id = None
                if vote.content_type == paper_content_type:
                    try:
                        paper = Paper.objects.get(id=vote.object_id)
                        unified_doc_id = paper.unified_document_id
                    except Paper.DoesNotExist:
                        continue
                elif vote.content_type == post_content_type:
                    try:
                        post = ResearchhubPost.objects.get(id=vote.object_id)
                        unified_doc_id = post.unified_document_id
                    except ResearchhubPost.DoesNotExist:
                        continue

                if unified_doc_id:
                    timestamp = int(vote.created_date.timestamp())
                    event_value = 1 if vote.vote_type == Vote.UPVOTE else -1
                    writer.writerow(
                        [vote.user_id, unified_doc_id, timestamp, "VOTE", event_value]
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {feed_entries.count()} view interactions and "
                f"{votes.count()} vote interactions"
            )
        )
