from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    """
    Adds a list of initial journal hubs to the database.
    """

    def handle(self, *args, **options):
        journals = [
            "arxiv",
            "biorxiv",
            "medrxiv",
            "chemrxiv",
            "research square",
            "osf preprints",
            "peerj",
            "authorea",
            "ssrn",
        ]
        for journal in journals:
            if not Hub.objects.filter(
                name=journal, namespace=Hub.Namespace.JOURNAL
            ).exists():
                print(f"Creating hub for journal {journal}")
                Hub.objects.create(name=journal, namespace=Hub.Namespace.JOURNAL)
