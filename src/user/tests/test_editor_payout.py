import datetime
from calendar import monthrange

from django.contrib.contenttypes.models import ContentType
from django.db.models import F
from rest_framework.test import APITestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution  # this is NOT the model
from reputation.distributor import Distributor
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.models import Permission
from user.editor_payout_tasks import get_daily_rsc_payout_amount_from_coin_gecko
from user.models import User
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

        self.setUpPayout()

    def setUpPayout(self):
        # Setting up static exchange rate for Coin Gecko to simulate payouts
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=1,
            real_rate=1,
            target_currency="USD",
        )
        RscExchangeRate.objects.all().update(
            created_date=datetime.datetime.now().replace(hour=14, minute=55)
        )

        # Code taken from editor_payout_tasks
        # Unable to run task directly because of missing API keys
        today = datetime.date.today()
        num_days_this_month = monthrange(today.year, today.month)[1]
        self.gecko_result = get_daily_rsc_payout_amount_from_coin_gecko(
            num_days_this_month
        )

        editors = User.objects.editors().annotate(
            editor_type=F("permissions__access_type")
        )

        for editor in editors.iterator():
            editor_type = editor.editor_type
            if editor_type == SENIOR_EDITOR:
                pay_amount = self.gecko_result["senior_pay_amount"]
            elif editor_type == ASSOCIATE_EDITOR:
                pay_amount = self.gecko_result["associate_pay_amount"]
            else:
                pay_amount = self.gecko_result["assistant_pay_amount"]

            distributor = Distributor(
                # this is NOT the model. It's a simple object
                Distribution("EDITOR_PAYOUT", pay_amount, False),
                editor,
                None,
                today,
            )
            distributor.distribute()

    def test_tiered_editors_payout(self):
        assistant_balance = self.assistant_editor.get_balance()
        associate_balance = self.associate_editor.get_balance()
        senior_balance = self.senior_editor.get_balance()

        self.assertGreater(associate_balance, assistant_balance)
        self.assertGreater(senior_balance, associate_balance)

        self.assertEqual(
            round(assistant_balance), round(self.gecko_result["assistant_pay_amount"])
        )
        self.assertEqual(
            round(associate_balance), round(self.gecko_result["associate_pay_amount"])
        )
        self.assertEqual(
            round(senior_balance), round(self.gecko_result["senior_pay_amount"])
        )
