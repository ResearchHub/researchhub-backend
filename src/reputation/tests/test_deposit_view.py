from rest_framework.test import APITestCase

from purchase.models import Wallet
from reputation.tests.helpers import ADDRESS_1, ADDRESS_2
from user.tests.helpers import create_random_authenticated_user


class DepositViewTests(APITestCase):
    def test_start_deposit_rsc_rejects_unlinked_from_address(self):
        user = create_random_authenticated_user("deposit_user")
        Wallet.objects.create(user=user, address=ADDRESS_1)
        other_user = create_random_authenticated_user("other_deposit_user")
        Wallet.objects.create(user=other_user, address=ADDRESS_2)

        self.client.force_authenticate(other_user)
        response = self.client.post(
            "/api/deposit/start_deposit_rsc/",
            {
                "amount": "100",
                "from_address": ADDRESS_1,
                "transaction_hash": "0x" + "a" * 64,
                "network": "BASE",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("from_address", response.data["detail"])

    def test_start_deposit_rsc_accepts_linked_from_address(self):
        user = create_random_authenticated_user("deposit_user")
        Wallet.objects.create(user=user, address=ADDRESS_1)

        self.client.force_authenticate(user)
        response = self.client.post(
            "/api/deposit/start_deposit_rsc/",
            {
                "amount": "100",
                "from_address": ADDRESS_1,
                "transaction_hash": "0x" + "b" * 64,
                "network": "BASE",
            },
        )

        self.assertEqual(response.status_code, 200)
