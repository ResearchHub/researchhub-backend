from ethereum.apps import w3, DEFAULT_PRIVATE_KEY, DEFAULT_ADDRESS
from ethereum.contracts import research_coin_contract


def get_client_version():
    return w3.clientVersion


def get_address():
    return DEFAULT_ADDRESS


def get_eth_balance(account):
    if account is None:
        account = get_address()
    return w3.eth.getBalance(account)


def get_rhc_balance(account):
    if account is None:
        account = get_address()
    return get_erc20_balance(research_coin_contract, account)


def get_erc20_balance(contract, account):
    return contract.functions.balanceOf(account).call()


def get_nonce(account):
    if account is None:
        account = get_address()
    return w3.eth.getTransactionCount(account)


def execute_erc20_transfer(contract, to, amount):
    """Sends `amount` of the token located at `contract` to `to`.

    !!! NOTE: This method should be used carefully because the default
    msg.sender is this server's default account.

    Attributes:
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

    Attributes:
        gas (int) - Amount of gas to fund transaction execution. Defaults to
            method_call.estimateGas()
        sender (str) - Address of message sender
        sender_signing_key (bytes) - Private key of sender
    """
    tx = method_call.buildTransaction({
        'from': sender or DEFAULT_ADDRESS,
        'nonce': get_nonce(None),
        'gas': gas or (get_gas_estimate(method_call) * 10),
    })
    signing_key = sender_signing_key or DEFAULT_PRIVATE_KEY
    signed = w3.eth.account.signTransaction(tx, signing_key)
    tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
    return tx_hash.hex()


def get_gas_estimate(method_call):
    return method_call.estimateGas()


def call(method_call, tx):
    """Returns the data from the contract's `method_call`."""
    return method_call.call()
