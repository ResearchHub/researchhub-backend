from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Runs all seeding commands related to research content"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip", nargs="*", default=[], help="Commands to skip (ex: --skip bounties grants)"
        )

    def handle(self, *args, **options):
        commands = [
            "seed_discussions",
            "seed_questions",
            "seed_hypotheses",
            "seed_preregistrations_with_fundraises",
            "seed_journal_papers",
            "seed_grants",
            "seed_bounties",
        ]

        for command in commands:
            if command in options["skip"]:
                continue

            self.stdout.write(f"Running {command}...")

            name, *args = command.split()

            call_command(name, *args)
