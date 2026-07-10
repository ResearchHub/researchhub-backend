from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from purchase.services.promotional_funds_service import PromotionalFundsService


class Command(BaseCommand):
    help = "Grant promotional funds (non-withdrawable, yield-earning RSC) to a user."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="User id or email")
        parser.add_argument("--amount", required=True, help="RSC amount to grant")
        parser.add_argument(
            "--reason", required=True, help="Campaign or grant reason (audited)"
        )

    def handle(self, *args, **options):
        User = get_user_model()  # noqa: N806

        identifier = options["user"]
        try:
            if identifier.isdigit():
                user = User.objects.get(id=int(identifier))
            else:
                user = User.objects.get(email=identifier)
        except User.DoesNotExist:
            raise CommandError(f"User not found: {identifier}")

        try:
            amount = Decimal(options["amount"])
        except InvalidOperation:
            raise CommandError(f"Invalid amount: {options['amount']}")

        try:
            record = PromotionalFundsService().grant(
                user, amount, reason=options["reason"]
            )
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(
            self.style.SUCCESS(
                f"Granted {amount} RSC promotional funds to user {user.id} "
                f"({user.email}); distribution id={record.id}"
            )
        )
