import os

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Runs all seeding commands related to the feed"

    def handle(self, *args, **options):
        journal_id_command = "set_journal_id"

        commands = [
            "create_feed_entries",
            journal_id_command,
            "populate_feed_entries --all",
            "refresh_feed",
            "opensearch index rebuild --force",
        ]

        for command in commands:
            if command == journal_id_command:
                self._set_journal_id()
            else:
                self.stdout.write(f"Running {command}...")

                name, *cmd_args = command.split()

                call_command(name, *cmd_args)

    def _set_journal_id(self):
        self.stdout.write(f"Setting placeholder Journal ID...")

        from hub.models import Hub

        try:
            journal_hub = Hub.objects.filter(namespace="journal").first()

            if journal_hub:
                self.stdout.write(
                    f"Using journal: {journal_hub.name} (ID: {journal_hub.id})"
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No journal found. Make sure to run seed commands first."
                    )
                )

                return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error fetching journal: {e}"))

            return

        from django.conf import settings

        keys_path = os.path.join(settings.BASE_DIR, "config_local", "keys.py")

        with open(keys_path) as f:
            content = f.read()

        updated = False
        lines = content.split("\n")
        key = "RESEARCHHUB_JOURNAL_ID"
        new_journal_id_line = f'{key} = "{journal_hub.id}"'

        for i, line in enumerate(lines):
            if not line.startswith(key):
                continue

            lines[i] = new_journal_id_line

            updated = True

            break

        if not updated:
            lines.append(new_journal_id_line)

        with open(keys_path, "w") as f:
            f.write("\n".join(lines))

        if updated:
            self.stdout.write(self.style.SUCCESS(f"{key} updated to {journal_hub.id}"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"{key} was not found in {keys_path}, so it's been added it with a value of {journal_hub.id}"
                )
            )
