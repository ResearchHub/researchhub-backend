'''
Creates an initial balance for pre-existing users
'''

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from reputation.models import Distribution
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
                balance_amount = self._get_user_balance(user)
                latest_distribution_id = user.reputation_records.order_by(
                    '-distributed_date'
                ).first().id
                Balance.objects.create(
                    user=user,
                    content_type=DISTRIBUTION_CONTENT_TYPE,
                    object_id=latest_distribution_id,
                    amount=balance_amount
                )
            except Exception as e:
                print(e)
                print(f'No distribution exists for {user.email}')

    def _get_user_balance(self, user):
        """Old method of calculating balance that is being used here for a one
        time conversion.
        """
        unpaid_distributions = user.reputation_records.filter(
            paid_status=None,
            distributed_status=Distribution.DISTRIBUTED
        )
        return (
            sum([u_d.amount for u_d in unpaid_distributions]),
            unpaid_distributions
        )
