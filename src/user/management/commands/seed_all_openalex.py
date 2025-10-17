from io import StringIO
from time import sleep

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

from utils.management import TeeStream


class Command(BaseCommand):
    help = "Runs all seeding commands related to OpenAlex"

    JOURNAL = "BIORXIV"
    TOPICS_COMMAND = "load_topics_from_openalex"
    PAPERS_ERROR = f"There are pending logs for this journal: {JOURNAL}"
    PAPERS_COMMAND = f"load_works_from_openalex --mode fetch --journal {JOURNAL}"
    TOPICS_ERROR = 'duplicate key value violates unique constraint "hub_hub_pkey"'

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of pages to process (default: 10)",
        )

    def handle(self, *args, **options):
        from math import ceil

        count_arg = f"--count {options['count']}"

        # The papers command is much slower than the others, so process half
        papers_count = ceil(options["count"] * 0.5)

        commands = [
            f"load_institutions_from_openalex {count_arg}",
            f"{self.TOPICS_COMMAND} {count_arg}",
            f"add_all_openalex_concepts {count_arg}",
            f"{self.PAPERS_COMMAND} --count {papers_count}",
        ]

        for command in commands:
            self._run_command(command)

            sleep(3)

    def _run_command(self, command, _retried=False):
        self.stdout.write(f"Running {command}...")

        name, *args = command.split()

        stdout_capture = StringIO()
        stderr_capture = StringIO()

        try:
            call_command(
                name,
                *args,
                stdout=TeeStream(self.stdout, stdout_capture),
                stderr=TeeStream(self.stderr, stderr_capture),
            )

            output = stdout_capture.getvalue() + stderr_capture.getvalue()

        except Exception as e:
            error_msg = str(e)

            self.stderr.write(error_msg)

            output = error_msg + stderr_capture.getvalue()

        if command.startswith(self.TOPICS_COMMAND) and self.TOPICS_ERROR in output:
            self._handle_topics_error(command, _retried)

        elif command.startswith(self.PAPERS_COMMAND) and self.PAPERS_ERROR in output:
            self._handle_papers_error(command, _retried)

    def _handle_topics_error(self, command, _retried):
        self.stdout.write(
            self.style.WARNING(
                f"Tried to run `{command}` but the Postgres sequence for "
                "hub_hub.id is out of sync and will be fixed first."
            )
        )

        if _retried:
            self.stdout.write(
                self.style.ERROR(f"Failed to run `{command}` after retrying")
            )

            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('"hub_hub"', 'id'),
                        COALESCE((SELECT MAX(id) FROM "hub_hub"), 1),
                        true
                    );
                    """
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed to reset Postgres sequence for hub_hub.id:\n{e}"
                )
            )

            return

        self.stdout.write(f"Postgres sequence reset. Retrying `{command}`...")

        self._run_command(command, _retried=True)

    def _handle_papers_error(self, command, _retried):
        self.stdout.write(
            self.style.WARNING(
                f"Tried to run `{command}` but there are lingering "
                "journals that need to be cleared out first."
            )
        )

        if _retried:
            self.stdout.write(
                self.style.ERROR(f"Failed to run `{command}` after retrying")
            )

            return

        self._run_command(f"fail_fetch_logs {self.JOURNAL}")

        self.stdout.write(f"Lingering journals cleared out. Retrying `{command}`...")

        self._run_command(command, _retried=True)
