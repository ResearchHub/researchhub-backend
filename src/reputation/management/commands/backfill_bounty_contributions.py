from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from reputation.models import Bounty, BountySolution, Contribution
from reputation.tasks import create_contribution


class Command(BaseCommand):
    def handle(self, *args, **options):
        bounty_content_type = ContentType.objects.get_for_model(Bounty)
        bounty_solution_content_type = ContentType.objects.get_for_model(BountySolution)
        bounties = Bounty.objects.all().iterator()
        bounty_solutions = BountySolution.objects.all().iterator()

        for bounty in bounties:
            user = bounty.created_by
            uni_doc = bounty.unified_document
            if not Contribution.objects.filter(
                object_id=bounty.id,
                content_type=bounty_content_type,
                user_id=user.id,
            ).exists():
                print(bounty)
                create_contribution(
                    Contribution.BOUNTY_CREATED,
                    {"app_label": "reputation", "model": "bounty"},
                    user.id,
                    uni_doc.id,
                    bounty.id,
                )

        for solution in bounty_solutions:
            user = solution.created_by
            uni_doc = solution.bounty.unified_document
            if not Contribution.objects.filter(
                object_id=solution.id,
                content_type=bounty_solution_content_type,
                user_id=user.id,
            ).exists():
                print(solution)
                create_contribution(
                    Contribution.BOUNTY_SOLUTION,
                    {"app_label": "reputation", "model": "bountysolution"},
                    user.id,
                    uni_doc.id,
                    solution.id,
                )
