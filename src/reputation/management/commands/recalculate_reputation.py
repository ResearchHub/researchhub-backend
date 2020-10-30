'''
Removes all unpaid distributions so they will not be eligible for withdrawal.
'''
from django.core.management.base import BaseCommand
from django.db.models import Sum

from purchase.models import Balance
from user.models import User

class Command(BaseCommand):

    def handle(self, *args, **options):
        balances = Balance.objects.all()
        users = User.objects.all()
        for i, user in enumerate(users):
          print('{} / {}'.format(i, users.count()))
          rep_sum = user.reputation_records.exclude(distribution_type='REFERRAL').aggregate(rep=Sum('amount'))
          print(rep_sum)
          rep = rep_sum.get('rep') or 0
          user.reputation = rep + 100
          user.save()
