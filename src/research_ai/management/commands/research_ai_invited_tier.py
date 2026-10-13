from django.core.management.base import BaseCommand, CommandError

from research_ai.services.usage_budget import (
    grant_invited_tier,
    resolve_ai_tier,
    revoke_invited_tier,
)
from user.constants.gatekeeper_constants import RESEARCH_AI_INVITED
from user.models import User
from user.related_models.gatekeeper_model import Gatekeeper


class Command(BaseCommand):
    help = (
        "Manually grant or revoke the Research AI invited tier ($10 a day) "
        "for existing users, by email."
    )

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["grant", "revoke", "list"])
        parser.add_argument("emails", nargs="*", help="Emails of existing users.")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "list":
            grants = Gatekeeper.objects.filter(
                type=RESEARCH_AI_INVITED, user__isnull=False
            ).select_related("user")
            for grant in grants.order_by("user__email"):
                self.stdout.write(grant.user.email)
            return

        if not options["emails"]:
            raise CommandError(f"{action} needs at least one email")

        change = grant_invited_tier if action == "grant" else revoke_invited_tier
        missing = []
        for email in options["emails"]:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                missing.append(email)
                continue
            changed = change(user)
            # The tier in effect can differ: staff stay privileged, registered
            # experts stay invited, suspended users stay blocked.
            self.stdout.write(
                f"{user.email}: {'updated' if changed else 'no change'}, "
                f"tier is now {resolve_ai_tier(user).name}"
            )
        if missing:
            raise CommandError(f"No user with email: {', '.join(missing)}")
