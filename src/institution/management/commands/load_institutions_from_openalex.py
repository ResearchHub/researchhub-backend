from django.core.management.base import BaseCommand

from institution.models import Institution
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = "Load Institutions from OpenAlex"

    def add_arguments(self, parser):
        parser.add_argument(
            "--page", default=1, type=int, help="Start at specific page number."
        )

    def handle(self, *args, **kwargs):
        page = kwargs["page"]
        open_alex = OpenAlex()

        current_page = page
        cursor = "*"
        while cursor:
            print("Processing page", current_page)
            institutions, cursor = open_alex.get_institutions(
                page=1, next_cursor=cursor
            )

            for institution in institutions:
                try:
                    Institution.upsert_from_openalex(institution)
                except Exception as e:
                    print(
                        "Failed to create institution:",
                        institution["id"],
                        "page:",
                        current_page,
                        "Exception:",
                        e,
                    )

            current_page += 1
