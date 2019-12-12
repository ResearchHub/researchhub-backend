from decimal import Decimal
from django.test import TestCase

from ethereum.utils import decimal_to_token_amount


class EthereumUtilsTests(TestCase):
    def setUp(self):
        self.denomination = 18

    def test_decimal_to_token_amount_with_floats(self):
        result_a = self.get_result('0.0')
        self.assertEqual(result_a, 0)
        result_b = self.get_result('0.01')
        self.assertEqual(result_b, 10000000000000000)
        c = '0.001'
        result_c = self.get_result(c)
        self.assertEqual(result_c, 1000000000000000)
        d = '1.0'
        result_d = self.get_result(d)
        self.assertEqual(result_d, 1000000000000000000)
        e = '1.00'
        result_e = self.get_result(e)
        self.assertEqual(result_e, 1000000000000000000)
        f = '1.000'
        result_f = self.get_result(f)
        self.assertEqual(result_f, 1000000000000000000)
        g = '1.001'
        result_g = self.get_result(g)
        self.assertEqual(result_g, 1001000000000000000)
        h = '1.01'
        result_h = self.get_result(h)
        self.assertEqual(result_h, 1010000000000000000)
        i = '1.1'
        result_i = self.get_result(i)
        self.assertEqual(result_i, 1100000000000000000)
        j = '1.10'
        result_j = self.get_result(j)
        self.assertEqual(result_j, 1100000000000000000)
        k = '10.0'
        result_k = self.get_result(k)
        self.assertEqual(result_k, 10000000000000000000)
        m = '11.0'
        result_m = self.get_result(m)
        self.assertEqual(result_m, 11000000000000000000)
        n = '11.01'
        result_n = self.get_result(n)
        self.assertEqual(result_n, 11010000000000000000)

    def test_decimal_to_token_amount_does_NOT_round(self):
        o = '111.5'
        result_o = self.get_result(o)
        self.assertEqual(result_o, 111500000000000000000)
        p = '111.56'
        result_p = self.get_result(p)
        self.assertEqual(result_p, 111560000000000000000)
        q = '111.04'
        result_q = self.get_result(q)
        self.assertEqual(result_q, 111040000000000000000)
        r = '115.045'
        result_r = self.get_result(r)
        self.assertEqual(result_r, 115045000000000000000)

    def test_decimal_to_token_amount_with_large_integer_part(self):
        s = '1150.045'
        result_s = self.get_result(s)
        self.assertEqual(result_s, 1150045000000000000000)
        t = '0011506.0'
        result_t = self.get_result(t)
        self.assertEqual(result_t, 11506000000000000000000)
        u = '864213579.0000'
        result_u = self.get_result(u)
        self.assertEqual(result_u, 864213579000000000000000000)
        # v = 715062.6
        # result_v = self.convert_to_big_integer(v, self.denomination)
        # self.assertEqual(result_v, (715062, 600000000000000000))

    def test_decimal_to_token_amount_with_large_decimal_part(self):
        w = '9999999999.999999999999999999'
        result_w = self.get_result(w)
        self.assertEqual(result_w, 9999999999999999999999999999)
        x = '000.9876543210'
        result_x = self.get_result(x)
        self.assertEqual(result_x, 987654321000000000)

    def get_result(self, amount_string):
        value = Decimal(amount_string)
        return decimal_to_token_amount(value, self.denomination)
