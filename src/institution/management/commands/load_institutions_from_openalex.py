from sqlite3 import IntegrityError

from django.core.management.base import BaseCommand

from institution.models import Institution
from utils.openalex import OpenAlex

# def


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
            print("institutions", len(institutions))
            print("cursor", cursor)

            if current_page == 3:
                return

            current_page += 1

        return

        for institution in institutions:
            try:
                print("Creating institution: " + institution["display_name"])
                Institution.objects.create(
                    openalex_id=institution["openalex_id"],
                    display_name=institution["display_name"],
                )
            except IntegrityError:
                print("Institution already exists: " + institution["display_name"])
