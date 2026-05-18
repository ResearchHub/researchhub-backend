from django.test import TestCase

from purchase.models import Wallet
from reputation.models import Deposit
from reputation.services.deposit_service import DepositService
from reputation.tests.helpers import ADDRESS_1, ADDRESS_2, create_deposit
from user.tests.helpers import create_random_authenticated_user


class DepositServiceTests(TestCase):
    def test_user_owns_wallet_address(self):
        user = create_random_authenticated_user("wallet_owner")
        Wallet.objects.create(user=user, address=ADDRESS_1)

        self.assertTrue(DepositService.user_owns_from_address(user, ADDRESS_1))

    def test_user_does_not_own_another_users_wallet_address(self):
        owner = create_random_authenticated_user("wallet_owner")
        other = create_random_authenticated_user("wallet_other")
        Wallet.objects.create(user=owner, address=ADDRESS_1)

        self.assertFalse(DepositService.user_owns_from_address(other, ADDRESS_1))

    def test_user_owns_address_from_prior_paid_deposit(self):
        user = create_random_authenticated_user("paid_deposit_user")
        deposit = create_deposit(user, from_address=ADDRESS_2)
        deposit.set_paid()

        self.assertTrue(DepositService.user_owns_from_address(user, ADDRESS_2))
