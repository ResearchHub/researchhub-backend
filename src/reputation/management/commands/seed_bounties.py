from time import time

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from reputation.distributions import Distribution
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee, Escrow
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user


class Command(BaseCommand):
    help = "Seed bounties"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count", type=int, default=6, help="Number of bounties to create"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} bounties...")

        # Create bounty fee if it doesn't exist
        BountyFee.objects.get_or_create(rh_pct=0.07, dao_pct=0.02)

        bounty_user = create_random_default_user("bounty_user")

        # Give RSC balance
        Distributor(
            Distribution("REWARD", 1000000, give_rep=False),
            bounty_user,
            bounty_user,
            time(),
            bounty_user,
        ).distribute()

        comment_user = create_random_default_user("comment_user")

        # Create bounties
        for i in range(options["count"]):
            amount = 100 * (i + 1)
            comment = create_rh_comment(created_by=comment_user)
            content_type = ContentType.objects.get_for_model(comment)

            Bounty.objects.create(
                amount=amount,
                item_object_id=comment.id,
                item_content_type_id=content_type.id,
                created_by=bounty_user,
                escrow=Escrow.objects.create(
                    created_by=bounty_user,
                    hold_type=Escrow.BOUNTY,
                    amount_holding=amount,
                    object_id=comment.id,
                    content_type=content_type,
                ),
                unified_document=comment.unified_document,
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
