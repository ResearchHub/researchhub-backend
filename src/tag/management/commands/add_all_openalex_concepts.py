from django.core.management.base import BaseCommand

from tag.models import Concept
from utils.openalex import OpenAlex
from utils.sentry import log_error


class Command(BaseCommand):
    def handle(self, *args, **options):
        oa = OpenAlex()
        res = oa.get_concepts()
        meta = res["meta"]
        next_cursor = meta["next_cursor"]

        while next_cursor:
            print(next_cursor)
            self._create_concepts(res["results"])
            res = oa.get_concepts(next_cursor)
            meta = res["meta"]
            next_cursor = meta["next_cursor"]

    def _create_concepts(self, concepts):
        for concept in concepts:
            try:
                description = concept.get("description", None)
                if description is None:
                    description = "No Description Available"
                data = {
                    "openalex_id": concept["id"],
                    "display_name": concept["display_name"],
                    "description": description,
                    "openalex_created_date": concept["created_date"],
                    "openalex_updated_date": concept["updated_date"],
                }
                Concept.create_or_update(data)
            except Exception as e:
                log_error(e)
