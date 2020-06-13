from decimal import Decimal
import json

from eth_keys import keys

from ethereum.apps import w3, DEFAULT_PRIVATE_KEY, DEFAULT_ADDRESS


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


def sign(message, private_key=DEFAULT_PRIVATE_KEY):
    sk = keys.PrivateKey(private_key)
    message = json.dumps(message)
    signature = sk.sign_msg(message)
    public_key = sk.public_key
    return signature, public_key
