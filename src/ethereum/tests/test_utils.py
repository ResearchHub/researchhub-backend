from decimal import Decimal
from django.test import TestCase

from ethereum.utils import decimal_to_big_integer


class EthereumUtilsTests(TestCase):
    def setUp(self):
        self.denomination = 18

    def test_float_to_big_integer_with_floats(self):
        a = 0.0
        result_a = self.convert_to_big_integer(a, self.denomination)
        self.assertEqual(result_a, (0, 0))
        b = 0.01
        result_b = self.convert_to_big_integer(b, self.denomination)
        self.assertEqual(result_b, (0, 10000000000000000))
        c = 0.001
        result_c = self.convert_to_big_integer(c, self.denomination)
        self.assertEqual(result_c, (0, 1000000000000000))
        d = 1.0
        result_d = self.convert_to_big_integer(d, self.denomination)
        self.assertEqual(result_d, (1, 0))
        e = 1.00
        result_e = self.convert_to_big_integer(e, self.denomination)
        self.assertEqual(result_e, (1, 0))
        f = 1.000
        result_f = self.convert_to_big_integer(f, self.denomination)
        self.assertEqual(result_f, (1, 0))
        g = 1.001
        result_g = self.convert_to_big_integer(g, self.denomination)
        self.assertEqual(result_g, (1, 1000000000000000))
        h = 1.01
        result_h = self.convert_to_big_integer(h, self.denomination)
        self.assertEqual(result_h, (1, 10000000000000000))
        i = 1.1
        result_i = self.convert_to_big_integer(i, self.denomination)
        self.assertEqual(result_i, (1, 100000000000000000))
        j = 1.10
        result_j = self.convert_to_big_integer(j, self.denomination)
        self.assertEqual(result_j, (1, 100000000000000000))
        k = 10.0
        result_k = self.convert_to_big_integer(k, self.denomination)
        self.assertEqual(result_k, (10, 0))
        m = 11.0
        result_m = self.convert_to_big_integer(m, self.denomination)
        self.assertEqual(result_m, (11, 0))
        n = 11.01
        result_n = self.convert_to_big_integer(n, self.denomination)
        self.assertEqual(result_n, (11, 10000000000000000))
        o = 111.5
        result_o = self.convert_to_big_integer(o, self.denomination)
        self.assertEqual(result_o, (111, 500000000000000000))
        p = 111.56
        result_p = self.convert_to_big_integer(p, self.denomination)
        self.assertEqual(result_p, (111, 560000000000000000))
        q = 111.04
        result_q = self.convert_to_big_integer(q, self.denomination)
        self.assertEqual(result_q, (111, 40000000000000000))
        r = 115.045
        result_r = self.convert_to_big_integer(r, self.denomination)
        self.assertEqual(result_r, (115, 45000000000000000))
        s = 1150.045
        result_s = self.convert_to_big_integer(s, self.denomination)
        self.assertEqual(result_s, (1150, 45000000000000000))
        t = 11506.0
        result_t = self.convert_to_big_integer(t, self.denomination)
        self.assertEqual(result_t, (11506, 0))
        u = 71506.0
        result_u = self.convert_to_big_integer(u, self.denomination)
        self.assertEqual(result_u, (71506, 0))
        v = 715062.6
        result_v = self.convert_to_big_integer(v, self.denomination)
        self.assertEqual(result_v, (715062, 600000000000000000))
        w = Decimal('9999999999.999999999999999999')
        result_w = self.convert_to_big_integer(w, self.denomination)
        self.assertEqual(result_w, (9999999999, 999999999999999999))
        x = 000.9876543210
        result_x = self.convert_to_big_integer(x, self.denomination)
        self.assertEqual(result_x, (0, 987654321000000000))

    def convert_to_big_integer(self, float_value, denomination):
        return decimal_to_big_integer(Decimal(str(float_value)), denomination)
