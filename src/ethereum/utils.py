from decimal import Decimal
import json

from eth_keys import keys, KeyAPI

from ethereum.apps import w3, DEFAULT_ADDRESS


def decimal_to_token_amount(value, denomination):
    if type(value) is not Decimal:
        raise TypeError('`value` must be of type Decimal')

    value_string = str(value)

    integer_string = value_string.split('.')[0]
    integer_pad_width = len(integer_string) + denomination
    integer_padded = integer_string.ljust(integer_pad_width, '0')
    integer_part = int(integer_padded)

    decimal_padded = value_string.split('.')[1].ljust(denomination, '0')
    decimal_part = int(decimal_padded)

    return integer_part + decimal_part


def get_client_version():
    return w3.clientVersion


def get_address():
    return DEFAULT_ADDRESS


def get_eth_balance(account=None):
    if account is None:
        account = get_address()
    return w3.eth.getBalance(account)


def get_erc20_balance(contract, account=None):
    if account is None:
        account = get_address()
    return contract.functions.balanceOf(account).call()


def get_nonce(account):
    if account is None:
        account = get_address()
    return w3.eth.getTransactionCount(account)


def get_fee_estimate(method_call):
    gas_estimate = get_gas_estimate(method_call)
    gas_price = w3.eth.generateGasPrice()
    return gas_estimate * gas_price


def get_gas_estimate(method_call):
    return method_call.estimateGas()


def call(method_call, tx):
    """Returns the data from the contract's `method_call`."""
    return method_call.call()


def sign_message(message, private_key: str) -> (str, bytes, str):
    """Returns tuple of signature, message, public key.

    Args:
        message (obj) -- Gets json stringified and converted to bytes.
        private_key (str) -- A hex string
    """
    sk_bytes = bytes.fromhex(private_key[2:])
    sk = keys.PrivateKey(sk_bytes)
    message = json.dumps(message)
    message_bytes = bytes(message, 'utf-8')
    signature = sk.sign_msg(message_bytes)
    signature_hex = signature.to_bytes().hex()
    public_key = sk.public_key
    public_key_hex = public_key.to_hex()
    return signature_hex, message_bytes, public_key_hex


def verify_signature(
    signature_hex: str,
    message_bytes: bytes,
    public_key_hex: str
):
    """Returns True for a valid signature.

    Args:
        signature (str) -- hex string
        message (bytes)
        public_key (str) -- hex string
    """
    signature_bytes = bytes.fromhex(signature_hex)
    signature = KeyAPI.Signature(signature_bytes=signature_bytes)
    pk_bytes = bytes.fromhex(public_key_hex[2:])
    pk = KeyAPI.PublicKey(pk_bytes)
    return signature.verify_msg(message_bytes, pk)
