from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from user.models import User
from purchase.models import Balance
from reputation.models import Distribution

BALANCE = 6000000
BANK_EMAIL = 'bank@researchhub.com'


class Command(BaseCommand):

    def handle(self, *args, **options):
        user = User.objects.filter(
            email=BANK_EMAIL
        )

        if not user.exists():
            print('Please sign in as bank user first')

        user = user.first()
        user_id = user.id
        content_type = ContentType.objects.get(model='distribution')
        proof_content_type = ContentType.objects.get(model='user')
        proof = {
            'table': 'user_user',
            'record': {'id': user_id, 'email': BANK_EMAIL}
        }

        distribution = Distribution.objects.create(
            amount=0,
            distribution_type='SIGN_UP',
            proof_item_content_type=proof_content_type,
            proof_item_object_id=user_id,
            proof=proof,
            recipient_id=user_id,
            distributed_status=Distribution.DISTRIBUTED
        )
        Balance.objects.create(
            user=user,
            amount=BALANCE,
            content_type=content_type,
            object_id=distribution.id
        )

    def sync_balance(self, user):
        # TODO: Implement balance sync with mutli-sig
        pass
