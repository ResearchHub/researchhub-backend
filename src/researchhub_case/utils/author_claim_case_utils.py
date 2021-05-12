import base64
import json
import time


# TODO: calvinhlee - maybe improve these in the future
def decode_validation_token(encoded_str):
    return base64.urlsafe_b64decode(encoded_str).decode("ascii")


def encode_validation_token(str):
    return base64.urlsafe_b64encode(str.encode("ascii"))


def format_valid_ids(case, requestor, target_author):
    return json.dumps({
        'case_id': case.id,
        'generated_time': int(time.time()),
        'requestor_id': requestor.id,
        'target_author_id': target_author.id,
    })


# TODO: calvinhlee - write email sender here
def send_validation_email(case):
    return True
