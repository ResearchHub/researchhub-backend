'''
Setting up watchdog watcher to read files from arxiv.
'''

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from reputation.lib import get_user_balance
from purchase.models import Balance
from user.models import User

DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model='distribution')


class Command(BaseCommand):

    def handle(self, *args, **options):
        excluded_users = Balance.objects.values_list(
            'user',
            flat=True
        ).distinct()
        users = User.objects.exclude(id__in=excluded_users)
        users_len = users.count()

        for i, user in enumerate(users):
            try:
                print(f'{i}/{users_len}')
                balance_amount = get_user_balance(user)
                first_distribution = user.reputation_records.first().id
                Balance.objects.create(
                    user=user,
                    content_type=DISTRIBUTION_CONTENT_TYPE,
                    object_id=first_distribution,
                    amount=balance_amount
                )
            except Exception as e:
                print(e)
                print(f'No distribution exists for {user.email}')
