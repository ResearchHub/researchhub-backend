import csv
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from paper.utils import format_raw_authors
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_unified_document_model import (
    UnifiedDocumentConcepts,
)


def parse_year_from_date(date_string):
    try:
        date_object = datetime.strptime(str(date_string), "%Y-%m-%d")
        year = date_object.year
        return year
    except ValueError:
        print("Failed to parse date", date_string)
        return None


def std_date(date_string, format="%Y-%m-%d"):
    try:
        date_object = datetime.strptime(str(date_string), format)
        return date_object.strftime(format)
    except ValueError:
        print("Failed to parse date", date_string)
        return None


def get_props_for_document(unified_doc):
    item_type = unified_doc.get_client_doc_type()
    specific_doc = unified_doc.get_document()  # paper, post, ...
    mapped = {
        "unified_document_id": str(unified_doc.id),
        "title": specific_doc.title,
        "slug": specific_doc.slug,
    }

    if item_type == "paper":
        paper = specific_doc
        mapped["pdf_license"] = paper.pdf_license
        mapped["oa_status"] = paper.oa_status
        mapped["authors"] = format_raw_authors(paper.raw_authors)
        mapped["journal"] = paper.external_source
        mapped["twitter_score"] = paper.twitter_score

        # Parse the authors' list to include only names
        authors_list = format_raw_authors(paper.raw_authors)
        names_only = [
            f"{author['first_name']} {author['last_name']}"
            for author in authors_list
            if author["first_name"] and author["last_name"]
        ]
        mapped["authors"] = ", ".join(names_only)

        if paper.paper_publish_date:
            mapped["publication_year"] = parse_year_from_date(paper.paper_publish_date)
            mapped["publication_timestamp"] = int(
                time.mktime(paper.paper_publish_date.timetuple())
            )

    else:
        authors_list = [
            f"{author.first_name} {author.last_name}"
            for author in unified_doc.authors
            if author.first_name and author.last_name
        ]
        mapped["authors"] = ", ".join(authors_list)

    # Add hubs
    hubs = unified_doc.hubs.all()
    relevant_hub_slugs = [f"{hub.slug}" for hub in hubs]
    mapped["hub_slugs"] = ";".join(relevant_hub_slugs)
    relevant_hubs = [f"{hub.name}" for hub in hubs]
    mapped["hubs"] = ";".join(relevant_hubs)

    primary_concept = (
        UnifiedDocumentConcepts.objects.filter(unified_document=unified_doc)
        .order_by("-relevancy_score")
        .first()
    )
    if primary_concept:
        mapped["primary_hub"] = primary_concept.concept.hub.name

    return mapped


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

            doc_props = get_props_for_document(doc)
            record = {**doc_props}
            record["item_id"] = item_type + "_" + str(specific_doc.id)
            record["item_type"] = item_type
            record["internal_item_id"] = str(specific_doc.id)
            record["created_timestamp"] = int(time.mktime(doc.created_date.timetuple()))

            if specific_doc.created_by:
                record["created_by_user_id"] = str(specific_doc.created_by.id)

            data.append(record)

        # Comments, Peer Reviews, ..
        comments = RhCommentModel.objects.filter(is_removed=False)
        for comment in comments:
            record = {}
            if comment.unified_document:
                doc_props = get_props_for_document(comment.unified_document)
                record = {**doc_props}

            record["item_id"] = "comment" + "_" + str(comment.id)
            record["item_type"] = "comment"
            record["item_subtype"] = comment.comment_type
            record["internal_item_id"] = str(comment.id)
            record["created_timestamp"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)

            bounties = comment.bounties.filter(status="OPEN").order_by("-amount")
            if bounties.exists():
                bounty = bounties.first()
                record["bounty_amount"] = bounty.amount
                record["bounty_id"] = str(bounty.id)
                record["bounty_type"] = bounty.bounty_type
                record["bounty_expiration_timestamp"] = int(
                    time.mktime(bounty.created_date.timetuple())
                )

            data.append(record)

        # Specify the filename
        filename = "exported_data.csv"

        # Define the header if required
        header = [
            "item_id",
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
            "created_timestamp",
            "publication_timestamp",
            "publication_year",
            "hubs",
            "hub_slugs",
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
