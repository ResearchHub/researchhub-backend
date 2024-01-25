import csv
import time

from django.core.management.base import BaseCommand

from analytics.utils.analytics_mapping_utils import build_doc_props_for_item
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument


class Command(BaseCommand):
    help = "Export item data to personalize"

    def handle(self, *args, **options):
        docs = ResearchhubUnifiedDocument.objects.filter(
            document_type__in=["PAPER", "DISCUSSION", "QUESTION", "PREREGISTRATION"],
            is_removed=False,
        )

        data = []
        for doc in docs:
            record = {}
            item_type = doc.get_client_doc_type()
            specific_doc = doc.get_document()  # paper, post, ...

            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = item_type + "_" + str(specific_doc.id)
            record["item_type"] = item_type
            record["internal_item_id"] = str(specific_doc.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))

            if specific_doc.created_by:
                record["created_by_user_id"] = str(specific_doc.created_by.id)

            data.append(record)

        # Comments, Peer Reviews, ..
        comments = RhCommentModel.objects.filter(is_removed=False)
        for comment in comments:
            record = {}
            if comment.unified_document:
                doc_props = build_doc_props_for_item(comment.unified_document)
                record = {**doc_props}

            record["ITEM_ID"] = "comment" + "_" + str(comment.id)
            record["item_type"] = "comment"
            record["item_subtype"] = comment.comment_type
            record["internal_item_id"] = str(comment.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)

            bounties = comment.bounties.filter(status="OPEN").order_by("-amount")
            if bounties.exists():
                bounty = bounties.first()
                record["bounty_amount"] = bounty.amount
                record["bounty_id"] = "bounty_" + str(bounty.id)
                record["bounty_type"] = bounty.bounty_type
                record["bounty_expiration_timestamp"] = int(
                    time.mktime(bounty.created_date.timetuple())
                )

            data.append(record)

        filename = "exported_data.csv"
        headers = [
            "ITEM_ID",
            "CREATION_TIMESTAMP",
            "item_type",
            "item_subtype",
            "internal_item_id",
            "unified_document_id",
            "created_by_user_id",
            "bounty_id",
            "bounty_amount",
            "bounty_type",
            "bounty_expiration_timestamp",
            "title",
            "journal",
            "pdf_license",
            "oa_status",
            "twitter_score",
            "slug",
            "authors",
            "updated_timestamp",
            "publication_timestamp",
            "publication_year",
            "hubs",
            "hub_slugs",
            "primary_hub",
        ]

        # Write to CSV
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=headers)

            # Write the header
            writer.writeheader()

            # Write the data
            for item in data:
                writer.writerow(item)

        self.stdout.write(
            self.style.SUCCESS(f"Successfully exported data to {filename}")
        )
