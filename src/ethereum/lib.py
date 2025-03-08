from decimal import Decimal

from django.conf import settings
from web3 import Web3

from utils.aws import create_client
from utils.web3_utils import web3_provider


def get_network_config(network="ethereum"):
    """Get the appropriate network configuration based on environment"""
    base_config = {
        "ethereum": {
            "mainnet": {
                "name": "ResearchCoin",
                "contract_address": settings.WEB3_RSC_ADDRESS,
                "ticker": "RSC",
                "denomination": 18,
                "reputation_exchange_rate": "1.0",
                "chain_id": 1,  # Ethereum mainnet
            },
            "testnet": {
                "name": "ResearchCoin",
                "contract_address": settings.WEB3_RSC_ADDRESS,
                "ticker": "RSC",
                "denomination": 18,
                "reputation_exchange_rate": "1.0",
                "chain_id": 11155111,  # Sepolia testnet
            },
        },
        "base": {
            "mainnet": {
                "name": "ResearchCoin",
                "contract_address": settings.WEB3_BASE_RSC_ADDRESS,
                "ticker": "RSC",
                "denomination": 18,
                "reputation_exchange_rate": "1.0",
                "chain_id": 8453,  # Base mainnet
            },
            "testnet": {
                "name": "ResearchCoin",
                "contract_address": settings.WEB3_BASE_RSC_ADDRESS,
                "ticker": "RSC",
                "denomination": 18,
                "reputation_exchange_rate": "1.0",
                "chain_id": 84532,  # Base Sepolia testnet
            },
        },
    }

    env = "mainnet" if settings.PRODUCTION else "testnet"
    return base_config[network][env]


TOKENS = {
    "RSC": {
        "ethereum": get_network_config("ethereum"),
        "base": get_network_config("base"),
    },
}

RSC_CONTRACT_ADDRESS = TOKENS["RSC"]["ethereum"]["contract_address"]


def get_token_config(token, network="ethereum"):
    """Get token configuration for specified network."""
    return TOKENS[token][network]


def get_token_address_choices():
    choices = []
    for token in TOKENS:
        for network in TOKENS[token]:
            config = TOKENS[token][network]
            choices.append(
                (config["contract_address"], f'{config["name"]} address ({network})')
            )
    return choices


TOKEN_ADDRESS_CHOICES = get_token_address_choices()


def convert_reputation_amount_to_token_amount(
    token, reputation_amount, network="ethereum"
):
    """Converts `reputation_amount` based on the `token` reputation exchange
    rate.

    Returns:
        (int, str) -- Amount of `token` in integer and decimal forms.
    """

    if reputation_amount < 0:
        raise ValueError("`reputation_amount` must be a positive number")

    token = get_token_config(token, network)
    rate = Decimal(str(token["reputation_exchange_rate"]))
    reputation = Decimal(str(reputation_amount))
    total = rate * reputation
    denomination = token["denomination"]
    return decimal_to_token_amount(total, denomination), str(total)


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


def get_nonce(w3, account):
    return w3.eth.get_transaction_count(account)


def get_gas_estimate(method_call):
    return 120000


def get_eth_balance(w3, account):
    return w3.eth.get_balance(account)


def get_fee_estimate(w3, method_call):
    """Returns fee estimate for `method_call` in wei based on estimateGas and
    generateGasPrice.
    """
    gas_estimate = get_gas_estimate(method_call)
    gas_price = w3.eth.generate_gas_price()  # wei
    return gas_estimate * gas_price


def execute_erc20_transfer(
    w3, sender, sender_signing_key, contract, to, amount, network="ETHEREUM"
):
    """Sends `amount` of the token located at `contract` to `to`.

    !!! NOTE: This method should be used carefully because it sends funds.

    Returns the transaction hash.

    Args:
        contract (obj) - w3 contract instance of the ERC20
        to (str) - Ethereum address of recipient
        amount (int) - Amount of token to send (in smallest possible
            denomination)
        network (str) - Network to use ("ETHEREUM" or "BASE")
    """
    decimals = contract.functions.decimals().call()
    decimal_amount = amount * 10 ** int(decimals)
    return _transact(
        w3,
        contract.functions.transfer(to, decimal_amount),
        sender,
        sender_signing_key,
        network=network,
    )


def _transact(
    w3, method_call, sender, sender_signing_key, network="ETHEREUM", gas=None
):
    """Executes the contract's `method_call` on chain."""
    gas_estimate = get_gas_estimate(method_call)
    checksum_sender = Web3.to_checksum_address(sender)

    chain_id = TOKENS["RSC"][network.lower()]["chain_id"]

    tx = method_call.build_transaction(
        {
            "from": checksum_sender,
            "nonce": get_nonce(w3, checksum_sender),
            "gas": gas or gas_estimate,
            "chainId": chain_id,
        }
    )

    signing_key = sender_signing_key
    signed = w3.eth.account.sign_transaction(tx, signing_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()


def get_private_key():
    client = create_client("secretsmanager")

    response = client.get_secret_value(SecretId=settings.WEB3_KEYSTORE_SECRET_ID)
    encrypted_key = response["SecretString"]

    response = client.get_secret_value(
        SecretId=settings.WEB3_KEYSTORE_PASSWORD_SECRET_ID
    )
    password = response["SecretString"]

    return web3_provider.ethereum.eth.account.decrypt(encrypted_key, password)
