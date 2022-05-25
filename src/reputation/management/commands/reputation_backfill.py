"""
Removes all unpaid distributions so they will not be eligible for withdrawal.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum

from user.models import User


class Command(BaseCommand):
    def handle(self, *args, **options):
        users = User.objects.filter(reputation__gt=100)
        total_changed_records = 0
        for i, user in enumerate(users):
            print("{} / {}".format(i, users.count()))
            rep = (
                user.reputation_records.exclude(distribution_type="REFERRAL")
                .exclude(distribution_type="PURCHASE")
                .exclude(distribution_type="REWARD")
                .exclude(distribution_type="EDITOR_COMPENSATION")
                .exclude(distribution_type="EDITOR_PAYOUT")
                .exclude(distribution_type="MOD_PAYOUT")
                .exclude(distribution_type="CREATE_BULLET_POINT")
                .exclude(distribution_type="CREATE_SUMMARY")
                .exclude(distribution_type="SUMMARY_UPVOTED")
                .exclude(distribution_type="BULLET_POINT_UPVOTED")
                .exclude(distribution_type="CREATE_FIRST_SUMMARY")
            )
            for j, record in enumerate(rep):
                if record.giver and record.giver.reputation < 110:
                    total_changed_records += 1
                    record.amount = 0

                gives_rep = {
                    "PAPER_UPVOTED": 1,
                    "THREAD_UPVOTED": 1,
                    "RESEARCHHUB_POST_UPVOTED": 1,
                    "REPLY_UPVOTED": 1,
                    "COMMENT_UPVOTED": 1,
                }

                removes_rep = {
                    "REPLY_DOWNVOTED": -1,
                    "COMMENT_DOWNVOTED": -1,
                    "THREAD_DOWNVOTED": -1,
                    "REPLY_CENSORED": -2,
                    "COMMENT_CENSORED": -2,
                    "THREAD_CENSORED": -2,
                }
                record.reputation_amount = gives_rep.get(
                    record.distribution_type, 0
                ) + removes_rep.get(record.distribution_type, 0)
                record.save()

            rep_sum = rep.aggregate(rep=Sum("reputation_amount"))
            rep = rep_sum.get("rep") or 0
            user.reputation = rep + 100
            try:
                user.save()
            except Exception as e:
                print(e)

        print("TOTAL CHANGED RECORDS: {}".format(total_changed_records))
