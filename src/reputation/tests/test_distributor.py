from time import time

from django.test import TestCase

from paper.tests.helpers import create_paper
from reputation.distributions import CreatePaper
from reputation.distributor import Distributor
from reputation.serializers import get_model_serializer
from utils.test_helpers import TestHelper


class DistributorTests(TestCase, TestHelper):

    def setUp(self):
        self.distributor = self.create_default_distributor()
        self.paper = create_paper()
        self.timestamp = time()
        self.paper_serializer = get_model_serializer(self.paper)

    def test_generate_proof(self):
        self.maxDiff = None

        proof = self.distributor.generate_proof(self.paper, self.timestamp)
        expected = {
            'timestamp': self.timestamp,
            'table': 'paper_paper',
            'record': self.paper_serializer(self.paper).data,
        }

        self.assertEqual(proof, expected)

    def create_default_distributor(self):
        user = self.create_random_default_user('Nymphadora Tonks')
        paper = create_paper(uploaded_by=user)
        timestamp = time()
        return Distributor(CreatePaper, paper.uploaded_by, paper, timestamp)
