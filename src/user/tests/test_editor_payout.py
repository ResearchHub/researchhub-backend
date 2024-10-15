from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.models import Permission
from user.editor_payout_tasks import editor_daily_payout_task
from user.tests.helpers import create_random_default_user


class PayoutTests(APITestCase):
    def setUp(self):
        # Create three users - an assistant, associate, and senior editor
        self.assistant_editor = create_random_default_user("assistant")
        self.associate_editor = create_random_default_user("associate")
        self.senior_editor = create_random_default_user("senior")
        self.hub = create_hub("hub_1")

        permissions = [
            (self.assistant_editor, ASSISTANT_EDITOR),
            (self.associate_editor, ASSOCIATE_EDITOR),
            (self.senior_editor, SENIOR_EDITOR),
        ]
        hub_content_type = ContentType.objects.get_for_model(Hub)

        for permission_group in permissions:
            user, permission = permission_group
            Permission.objects.create(
                access_type=permission,
                content_type=hub_content_type,
                object_id=self.hub.id,
                user=user,
            )

        # Setting up static exchange rate for Coin Gecko to simulate payouts
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=1,
            real_rate=1,
            target_currency="USD",
        )

    def test_tiered_editors_payout(self):
        editor_daily_payout_task()

        assistant_balance = self.assistant_editor.get_balance()
        associate_balance = self.associate_editor.get_balance()
        senior_balance = self.senior_editor.get_balance()
        print(associate_balance, associate_balance, senior_balance)
        self.assertGreater(associate_balance, assistant_balance)
        self.assertGreater(senior_balance, associate_balance)
