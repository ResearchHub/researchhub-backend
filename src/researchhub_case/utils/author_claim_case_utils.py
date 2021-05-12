import base64
import json
import time
import uuid


def decode_validation_token(encoded_str):
    return base64.urlsafe_b64decode(encoded_str).decode("ascii")


def encode_validation_token(str):
    return base64.urlsafe_b64encode(str.encode("ascii"))


def get_formatted_token(generated_time):
    return json.dumps({
        "generated_time": generated_time,
        "token": uuid.uuid4().hex,
    })


def get_new_validation_token():
    generated_time = int(time.time())
    token = encode_validation_token(get_formatted_token(generated_time))
    return [
        generated_time,
        token
    ]


# TODO: calvinhlee - write email sender here
def send_validation_email(case):
    return True
