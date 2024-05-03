from django.core.management.base import BaseCommand

from topic.models import Topic
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = "Load Topics from OpenAlex"

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
            topics, cursor = open_alex.get_topics(page=1, next_cursor=cursor)

            print("topics", topics)

            for topic in topics:
                try:
                    Topic.upsert_from_openalex(topic)
                except Exception as e:
                    print(
                        "Failed to create topic:",
                        topic["id"],
                        "page:",
                        current_page,
                        "Exception:",
                        e,
                    )

            current_page += 1
