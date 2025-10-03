from django.core.management.base import BaseCommand

from tag.models import Concept
from utils.openalex import OpenAlex
from utils.sentry import log_error


class Command(BaseCommand):
    help = "Load Concepts from OpenAlex"

    def handle(self, *args, **options):
        oa = OpenAlex()
        res = oa.get_concepts()
        meta = res["meta"]
        next_cursor = meta["next_cursor"]

        try:
            while next_cursor:
                self.stdout.write(next_cursor)

                self._create_concepts(res["results"])

                res = oa.get_concepts(next_cursor)
                meta = res["meta"]
                next_cursor = meta["next_cursor"]

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopped by user"))

    def _create_concepts(self, concepts):
        for concept in concepts:
            try:
                description = concept.get("description", None)

                Concept.create_or_update({
                    "openalex_id": concept["id"],
                    "display_name": concept["display_name"],
                    "description": "No Description Available" if description is None else description,
                    "openalex_created_date": concept["created_date"],
                    "openalex_updated_date": concept["updated_date"],
                })

            except Exception as e:
                log_error(e)
