from django.test import TestCase

from ethereum.lib import convert_reputation_amount_to_token_amount


class EthereumLibTests(TestCase):
    def setUp(self):
        self.token_ticker = 'rhc'

    def test_convert_reputation_amount_to_token_amount(self):
        rep = 1
        res = convert_reputation_amount_to_token_amount(self.token_ticker, rep)
        self.assertEqual(res, 100000000000000000)
        rep = 12
        res = convert_reputation_amount_to_token_amount(self.token_ticker, rep)
        self.assertEqual(res, 1200000000000000000)
        rep = 210
        res = convert_reputation_amount_to_token_amount(self.token_ticker, rep)
        self.assertEqual(res, 21000000000000000000)

    def test_convert_reputation_amount_to_token_amount_with_negatives(self):
        rep = -5
        with self.assertRaises(ValueError):
            convert_reputation_amount_to_token_amount(self.token_ticker, rep)
