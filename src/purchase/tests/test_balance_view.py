import csv
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from purchase.related_models.balance_model import Balance
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from user.tests.helpers import create_random_authenticated_user


class BalanceViewTests(APITestCase):

    def setUp(self):
        self.user = create_random_authenticated_user("balance_user")
        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        vote_content_type = ContentType.objects.get(model="vote", app_label="paper")
        self.transaction = Balance.objects.create(
            amount=1000, user=self.user, content_type=vote_content_type
        )

    def test_list_csv(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get("/api/transactions/list_csv/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="transactions.csv"',
        )

        content = response.content.decode("utf-8")
        csv_file = StringIO(content)
        reader = csv.reader(csv_file)
        expected = [
            ["date", "rsc_amount", "rsc_to_usd", "usd_value", "description"],
            [
                self.transaction.created_date.isoformat(
                    timespec="microseconds", sep=" "
                ),
                str(self.transaction.amount),
                str(self.rsc_exchange_rate.real_rate),
                f"{self.transaction.amount*self.rsc_exchange_rate.real_rate:.2f}",
                self.transaction.content_type.name,
            ],
        ]
        actual = list(reader)
        self.assertEqual(expected, actual)
