"""
Removes all unpaid distributions so they will not be eligible for withdrawal.
"""

from django.core.management.base import BaseCommand

from discussion.reaction_models import Vote as ReactionVote
from reputation.models import Distribution


class Command(BaseCommand):
    def handle(self, *args, **options):
        objects = Distribution.objects.all()

        for i, rep in enumerate(objects):
            giver = None
            if rep.proof_item:
                content_type = rep.proof_item_content_type.model_class()
                if content_type is ReactionVote:
                    giver = rep.proof_item.created_by

                if giver:
                    rep.giver = giver
                    print(rep)
                    rep.save()
