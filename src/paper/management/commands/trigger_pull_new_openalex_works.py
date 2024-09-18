from django.core.management.base import BaseCommand

from paper.tasks import pull_new_openalex_works


class Command(BaseCommand):
    help = "Triggers the pull_new_openalex_works task"

    def handle(self, *args, **options):
        self.stdout.write("Triggering pull_new_openalex_works task...")
        pull_new_openalex_works()
        self.stdout.write(
            self.style.SUCCESS("Successfully triggered pull_new_openalex_works task")
        )
