from django.test import TestCase

from reputation.models import Distribution
from reputation.distributions import CreatePaper
from utils.test_helpers import TestHelper


class ModelTests(TestCase, TestHelper):

    def setUp(self):
        pass

    def test_string_representation(self):
        user = self.create_user()
        distribution = Distribution.objects.create(
            recipient=user,
            amount=1,
            distribution_type=CreatePaper.name,
            proof='proof',
            proof_item=user
        )
        self.assertEqual(
            str(distribution),
            f'Distribution: CREATE_PAPER, Recipient: {user}, Amount: 1'
        )
