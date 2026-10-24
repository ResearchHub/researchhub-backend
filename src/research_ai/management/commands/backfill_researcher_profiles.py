"""
Queue researcher-profile builds for users who already use the AI chats.

New chats trigger a build on their own; this covers users whose chats predate
``ResearcherProfile``. Each queued build is an LLM run charged to that user's
Research AI budget, and is a no-op when their profile is already current.

Usage:
    python manage.py backfill_researcher_profiles --dry-run
    python manage.py backfill_researcher_profiles --limit 100
    python manage.py backfill_researcher_profiles --user-ids 73794,1234
"""

from django.core.management.base import BaseCommand, CommandError

from research_ai.models import AgentConversation
from research_ai.services.notebook_chat import ASSISTANT_WORKFLOW, WORKFLOW
from research_ai.tasks import ensure_researcher_profile_task


class Command(BaseCommand):
    help = "Queue researcher-profile builds for existing AI chat users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-ids",
            type=str,
            help="Comma-separated user ids to queue instead of all chat users.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Queue at most this many users.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many users would be queued without queueing.",
        )

    def handle(self, *args, **options):
        user_ids = self._user_ids(options)
        if options["dry_run"]:
            self.stdout.write(f"Would queue {len(user_ids)} researcher profile(s).")
            return
        for user_id in user_ids:
            ensure_researcher_profile_task.delay(user_id)
        self.stdout.write(
            self.style.SUCCESS(f"Queued {len(user_ids)} researcher profile(s).")
        )

    def _user_ids(self, options) -> list[int]:
        if options["user_ids"]:
            try:
                return [int(value) for value in options["user_ids"].split(",") if value]
            except ValueError as e:
                raise CommandError("--user-ids must be comma-separated ints.") from e
        user_ids = (
            AgentConversation.objects.filter(
                workflow__in=(WORKFLOW, ASSISTANT_WORKFLOW),
                is_removed=False,
                user__isnull=False,
            )
            .order_by("user_id")
            .values_list("user_id", flat=True)
            .distinct()
        )
        if options["limit"] is not None:
            user_ids = user_ids[: options["limit"]]
        return list(user_ids)
