from django.test import TestCase

from ethereum.lib import convert_reputation_amount_to_token_amount


class EthereumLibTests(TestCase):
    def setUp(self):
        self.token_ticker = 'RSC'

    def test_convert_reputation_amount_to_token_amount(self):
        rep = 1
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 1000000000000000000)
        self.assertEqual(decimal, '1.0')
        rep = 12
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 12000000000000000000)
        self.assertEqual(decimal, '12.0')
        rep = 210
        integer, decimal = convert_reputation_amount_to_token_amount(
            self.token_ticker,
            rep
        )
        self.assertEqual(integer, 210000000000000000000)
        self.assertEqual(decimal, '210.0')

    def test_convert_reputation_amount_to_token_amount_with_negatives(self):
        rep = -5
        with self.assertRaises(ValueError):
            convert_reputation_amount_to_token_amount(self.token_ticker, rep)
