import base64
import time

# TODO: calvinhlee - improve this in the future
def decode_validation_token(encoded_str):
    return base64.urlsafe_b64decode(encoded_str)


def encode_validation_token(str):
    return base64.urlsafe_b64encode(str)


def format_valid_ids(case, requestor, target_author):
    return '&'.join([
      f'case_id={case.id}',
      f'&requestor_id={requestor.id}',
      f'&target_author_id={target_author}'
      f'&generated_time={int(time.time())}'
    ])


def send_validation_email(case):
    return True
