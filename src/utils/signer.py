from django.core import signing


def encode_signed_value(value):
    return signing.dumps(value)


def decode_signed_value(signed_value, max_age=None):
    try:
        return signing.loads(signed_value, max_age=max_age)
    except signing.BadSignature:
        return None
