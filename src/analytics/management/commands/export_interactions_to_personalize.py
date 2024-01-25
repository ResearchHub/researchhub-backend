import csv

from django.core.management.base import BaseCommand

from analytics.utils.analytics_mapping_utils import build_bounty_event, build_vote_event
from discussion.reaction_models import Vote
from user.models import Action


class Command(BaseCommand):
    help = "Export user interaction data to personalize"

    def handle(self, *args, **options):
        actions = (
            Action.objects.all()
            .filter(is_removed=False, user__isnull=False)
            .select_related(
                "content_type",
                "user",
            )
            .prefetch_related(
                "item",
                "hubs",
                "user__author_profile",
            )
        )

        data = []
        for action in actions:
            if action.content_type.model == "bounty":
                event = build_bounty_event(action)
                data.append(event)
            elif action.content_type.model == "vote":
                if action.item.vote_type == Vote.DOWNVOTE:
                    # Skip downvotes since they are not beneficial for machine learning models
                    continue

                event = build_vote_event(action)
                data.append(event)

        # Specify the filename
        filename = "exported_interaction_data.csv"

        # Define the header if required
        header = [
            "ITEM_ID",
            "EVENT_TYPE",
            "TIMESTAMP",
            "EVENT_VALUE",
            "USER_ID",
            "internal_item_id",
            "unified_document_id",
            "primary_hub",
        ]

        # Write to CSV
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=header)

            # Write the header
            writer.writeheader()

            # Write the data
            for item in data:
                writer.writerow(item)

        self.stdout.write(
            self.style.SUCCESS(f"Successfully exported data to {filename}")
        )
