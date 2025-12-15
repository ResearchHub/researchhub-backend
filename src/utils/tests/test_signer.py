from django.test import TestCase

from utils.signer import decode_signed_value, encode_signed_value


class SignerTests(TestCase):
    def test_encode_decode_roundtrip(self):
        value = 12345
        signed = encode_signed_value(value)
        self.assertEqual(decode_signed_value(signed), value)

    def test_decode_returns_none_for_invalid(self):
        self.assertIsNone(decode_signed_value("invalid"))
        self.assertIsNone(decode_signed_value(""))

    def test_decode_returns_none_when_expired(self):
        signed = encode_signed_value(123)
        self.assertIsNone(decode_signed_value(signed, max_age=0))

    def test_works_with_strings(self):
        value = "test-string"
        signed = encode_signed_value(value)
        self.assertEqual(decode_signed_value(signed), value)

    def test_works_with_dicts(self):
        value = {"user_id": 123, "action": "connect"}
        signed = encode_signed_value(value)
        self.assertEqual(decode_signed_value(signed), value)

