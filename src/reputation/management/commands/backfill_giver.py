"""
Removes all unpaid distributions so they will not be eligible for withdrawal.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum

from discussion.models import Vote as ReactionVote
from paper.models import Vote
from reputation.models import Distribution
from user.models import User


class Command(BaseCommand):
    def handle(self, *args, **options):
        objects = Distribution.objects.all()
        total_changed_records = 0
        count = objects.count()
        for i, rep in enumerate(objects):
            giver = None
            if rep.proof_item:
                content_type = rep.proof_item_content_type.model_class()
                if content_type is Vote:
                    giver = rep.proof_item.created_by
                elif content_type is ReactionVote:
                    giver = rep.proof_item.created_by

                if giver:
                    rep.giver = giver
                    print(rep)
                    rep.save()
            # print("{} / {}".format(i, count))
            # rep = user.reputation_records.exclude(distribution_type="REFERRAL")
            # for record in rep:
            #     if record.recipient.reputation <= 110:
            #         total_changed_records += 1
            #         print(record)
            #         record.amount = 0
            #         record.save()
