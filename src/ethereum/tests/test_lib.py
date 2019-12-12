from django.test import TestCase

from ethereum.lib import convert_reputation_amount_to_token_amount


class EthereumLibTests(TestCase):
    def setUp(self):
        self.token_ticker = 'rhc'

    def test_convert_reputation_amount_to_token_amount(self):
        rep = 1
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 100000000000000000)
        self.assertEqual(decimal, '0.1')
        rep = 12
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 1200000000000000000)
        self.assertEqual(decimal, '1.2')
        rep = 210
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 21000000000000000000)
        self.assertEqual(decimal, '21.0')

    def test_convert_reputation_amount_to_token_amount_with_negatives(self):
        rep = -5
        with self.assertRaises(ValueError):
            convert_reputation_amount_to_token_amount(self.token_ticker, rep)
