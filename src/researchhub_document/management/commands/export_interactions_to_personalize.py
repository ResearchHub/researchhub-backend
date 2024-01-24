import csv
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from paper.utils import format_raw_authors
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Action


def get_hub_props(action):
    hubs = action.hubs.all()
    hubs_list = hubs.values_list("name", flat=True)
    hub_slug_list = hubs.values_list("slug", flat=True)

    return {
        "hubs": ",".join(hubs_list),
        "hub_slugs": ",".join(hub_slug_list),
    }


def create_bounty_event(action):
    bounty = action.item
    is_contribution = (
        str(bounty.created_by_id) == str(action.user_id) and bounty.parent is not None
    )
    hub_props = get_hub_props(action)

    record = {**hub_props}
    record["item_id"] = str(bounty.id)
    record["user_id"] = str(action.user_id)
    record["amount_offered"] = bounty.amount
    record["event_type"] = "bounty_contributed" if is_contribution else "bounty_created"

    if bounty.unified_document:
        specific_doc = bounty.unified_document.get_document()
        item_type = bounty.unified_document.get_client_doc_type()
        record["unified_document_id"] = str(bounty.unified_document.id)
        record["related_item_id"] = str(specific_doc.id)
        record["related_item_type"] = item_type

    return record


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
                event = create_bounty_event(action)
                data.append(event)

        # Specify the filename
        filename = "exported_interaction_data.csv"

        # Define the header if required
        header = [
            "item_id",
            "user_id",
            "event_type",
            "amount_offered",
            "unified_document_id",
            "related_item_id",
            "related_item_type",
            "hubs",
            "hub_slugs",
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
