import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    actions = ["backup", "restore"]
    help = "Backup or restore seeded database data"

    @property
    def path(self):
        return os.path.join(
            os.path.dirname(settings.BASE_DIR), ".seeded_db_backup.json"
        )

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=self.actions,
            help="Specify whether to perform a backup or restore operation.",
        )

    def handle(self, *args, **options):
        if options["action"] == "backup":
            self._backup()

        elif options["action"] == "restore":
            self._restore()

        else:  # Not possible, but don't leave it open-ended
            self.stdout.write(
                self.style.ERROR(
                    f"Invalid action specified. Expected one of:\n{', '.join(self.actions)}"
                )
            )

    def _backup(self):
        self.stdout.write("Backing up seeded database...")

        if os.path.exists(self.path):
            os.remove(self.path)

        from django.core.management import call_command

        with open(self.path, "w") as f:
            call_command("dumpdata", stdout=f, indent=2)

        self.stdout.write(f"Database backed up to:\n{self.path}")

    def _restore(self):
        if not os.path.exists(self.path):
            self.stdout.write(
                self.style.ERROR(
                    f"Database backup does not exist. Expected:\n{self.path}"
                )
            )

            return

        self.stdout.write("Restoring seeded database...")

        call_command("flush", interactive=False)
        call_command("loaddata", self.path)

        self.stdout.write(f"Database restored from:\n{self.path}")
