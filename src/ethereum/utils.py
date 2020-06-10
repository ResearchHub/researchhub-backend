from decimal import Decimal
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


def execute_erc20_transfer(contract, to, amount):
    """Sends `amount` of the token located at `contract` to `to`.

    !!! NOTE: This method should be used carefully because the default
    msg.sender is this server's default account.

    Returns the transaction hash.

    Args:
        contract (obj) - w3 contract instance of the ERC20
        to (str) - Ethereum address of recipient
        amount (int) - Amount of token to send (in smallest possible
            denomination)
    """
    return transact(contract.functions.transfer(to, amount))


def transact(method_call, gas=None, sender=None, sender_signing_key=None):
    """Executes the contract's `method_call` on chain.

    !!! NOTE: This method should be used carefully because the default
    msg.sender is this server's default account.

    Args:
        gas (int) - Amount of gas to fund transaction execution. Defaults to
            method_call.estimateGas()
        sender (str) - Address of message sender
        sender_signing_key (bytes) - Private key of sender
    """
    tx = method_call.buildTransaction({
        'from': sender or DEFAULT_ADDRESS,
        'nonce': get_nonce(None),
        'gas': gas or (get_gas_estimate(method_call) * 2),
    })
    signing_key = sender_signing_key or DEFAULT_PRIVATE_KEY
    signed = w3.eth.account.signTransaction(tx, signing_key)
    tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
    return tx_hash.hex()


def get_fee_estimate(method_call):
    gas_estimate = get_gas_estimate(method_call)
    gas_price = w3.eth.generateGasPrice()
    return gas_estimate * gas_price


def get_gas_estimate(method_call):
    return method_call.estimateGas()


def call(method_call, tx):
    """Returns the data from the contract's `method_call`."""
    return method_call.call()
