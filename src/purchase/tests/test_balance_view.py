import csv
from io import StringIO
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from purchase.related_models.balance_model import Balance
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Withdrawal
from user.tests.helpers import create_random_authenticated_user


class BalanceViewTests(APITestCase):

    def setUp(self):
        self.user = create_random_authenticated_user("balance_user")
        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=Decimal('0.5'),
            real_rate=Decimal('0.5'),
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        vote_content_type = ContentType.objects.get(
            model="vote", app_label="discussion"
        )
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
                    timespec="microseconds",
                    sep=" "
                ),
                str(self.transaction.amount),
                str(self.rsc_exchange_rate.real_rate),
                f"{self.transaction.amount*self.rsc_exchange_rate.real_rate:.2f}",
                self.transaction.content_type.name,
            ],
        ]
        actual = list(reader)
        self.assertEqual(expected, actual)

    def test_turbotax_csv_export(self):
        # Arrange
        self.client.force_authenticate(self.user)
        
        # Create additional test transactions with different types
        withdrawal_type = ContentType.objects.get_or_create(
            model="withdrawal", app_label="reputation"
        )[0]
        deposit_type = ContentType.objects.get_or_create(
            model="deposit", app_label="purchase"
        )[0]
        fee_type = ContentType.objects.get_or_create(
            model="transaction_fee", app_label="purchase"
        )[0]

        # Create test transactions
        Balance.objects.create(
            amount=-500,  # Negative amount for withdrawal
            user=self.user,
            content_type=withdrawal_type
        )
        Balance.objects.create(
            amount=200,  # Positive amount for deposit
            user=self.user,
            content_type=deposit_type
        )
        Balance.objects.create(
            amount=-50,  # Negative amount for fee
            user=self.user,
            content_type=fee_type
        )
        
        # Create a failed withdrawal that should be excluded
        from reputation.models import Withdrawal
        failed_source = Withdrawal.objects.create(
            amount=-300,
            paid_status='FAILED',
            user=self.user
        )
        failed_withdrawal = Balance.objects.create(
            amount=-300,
            user=self.user,
            content_type=withdrawal_type,
            object_id=failed_source.id
        )

        # Act
        response = self.client.get("/api/transactions/turbotax_csv_export/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="transactions_turbotax.csv"'
        )

        content = response.content.decode("utf-8")
        csv_file = StringIO(content)
        reader = csv.reader(csv_file)
        rows = list(reader)

        # Verify header
        expected_header = [
            "Date", "Type", "Sent Asset", "Sent Amount", "Received Asset",
            "Received Amount", "Fee Asset", "Fee Amount",
            "Market Value Currency", "Market Value", "Description",
            "Transaction Hash", "Transaction ID"
        ]
        self.assertEqual(rows[0], expected_header)

        # Verify transaction count (4 total, minus 1 failed)
        self.assertEqual(len(rows), 5)  # Header + 4 transactions - 1 failed

        # Verify transaction types and ensure failed withdrawal is excluded
        transaction_types = [row[1] for row in rows[1:]]
        transaction_ids = [row[-1] for row in rows[1:]]
        
        self.assertIn("Income", transaction_types)  # For positive amounts
        self.assertIn("Withdrawal", transaction_types)  # For withdrawal
        self.assertIn("Expense", transaction_types)  # For fee
        self.assertNotIn(str(failed_withdrawal.id), transaction_ids)

        # Verify amounts and calculations
        for row in rows[1:]:
            # Check if required fields are present
            self.assertTrue(row[9])  # Market Value should not be empty
            
            # Verify market value calculation
            if row[3]:  # Sent Amount
                amount = Decimal(row[3])
                market_value = Decimal(row[9])
                self.assertAlmostEqual(
                    market_value,
                    amount * self.rsc_exchange_rate.real_rate,
                    places=2
                )
            elif row[5]:  # Received Amount
                amount = Decimal(row[5])
                market_value = Decimal(row[9])
                self.assertAlmostEqual(
                    market_value,
                    amount * self.rsc_exchange_rate.real_rate,
                    places=2
                )
