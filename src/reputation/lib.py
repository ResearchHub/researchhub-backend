import decimal
import logging
import math
import os
from datetime import datetime
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from web3 import Web3

from ethereum.lib import (
    RSC_CONTRACT_ADDRESS,
    execute_erc20_transfer,
    get_private_key,
)
from mailing_list.services import EmailService
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from reputation.services.hot_wallet_service import HotWalletService
from utils.web3_utils import web3_provider

WITHDRAWAL_MINIMUM = int(os.environ.get("WITHDRAWAL_MINIMUM", 500))
WITHDRAWAL_PER_TWO_WEEKS = 100000

logger = logging.getLogger(__name__)

contract_abi = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "creationBlock",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_amount", "type": "uint256"},
        ],
        "name": "transferFrom",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_newController", "type": "address"}],
        "name": "changeController",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_blockNumber", "type": "uint256"},
        ],
        "name": "balanceOfAt",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "version",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_cloneTokenName", "type": "string"},
            {"name": "_cloneDecimalUnits", "type": "uint8"},
            {"name": "_cloneTokenSymbol", "type": "string"},
            {"name": "_snapshotBlock", "type": "uint256"},
            {"name": "_transfersEnabled", "type": "bool"},
        ],
        "name": "createCloneToken",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "parentToken",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_amount", "type": "uint256"},
        ],
        "name": "generateTokens",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_blockNumber", "type": "uint256"}],
        "name": "totalSupplyAt",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "transfersEnabled",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "parentSnapShotBlock",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_amount", "type": "uint256"},
            {"name": "_extraData", "type": "bytes"},
        ],
        "name": "approveAndCall",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_amount", "type": "uint256"},
        ],
        "name": "destroyTokens",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_token", "type": "address"}],
        "name": "claimTokens",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "tokenFactory",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_transfersEnabled", "type": "bool"}],
        "name": "enableTransfers",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "controller",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "_tokenFactory", "type": "address"},
            {"name": "_parentToken", "type": "address"},
            {"name": "_parentSnapShotBlock", "type": "uint256"},
            {"name": "_tokenName", "type": "string"},
            {"name": "_decimalUnits", "type": "uint8"},
            {"name": "_tokenSymbol", "type": "string"},
            {"name": "_transfersEnabled", "type": "bool"},
        ],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {"payable": True, "stateMutability": "payable", "type": "fallback"},
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "_token", "type": "address"},
            {"indexed": True, "name": "_controller", "type": "address"},
            {"indexed": False, "name": "_amount", "type": "uint256"},
        ],
        "name": "ClaimedTokens",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "_from", "type": "address"},
            {"indexed": True, "name": "_to", "type": "address"},
            {"indexed": False, "name": "_amount", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "_cloneToken", "type": "address"},
            {"indexed": False, "name": "_snapshotBlock", "type": "uint256"},
        ],
        "name": "NewCloneToken",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "_owner", "type": "address"},
            {"indexed": True, "name": "_spender", "type": "address"},
            {"indexed": False, "name": "_amount", "type": "uint256"},
        ],
        "name": "Approval",
        "type": "event",
    },
]


def _get_private_key_for_transfer():
    if not settings.WEB3_KEYSTORE_SECRET_ID:
        return None

    try:
        return get_private_key()
    except Exception:
        logger.exception("Error retrieving private key for transfer")
        return None


def _get_w3_for_network(network):
    return web3_provider.ethereum if network == "ETHEREUM" else web3_provider.base


def broadcast_withdrawal_transfer(withdrawal):
    """
    Broadcast the ERC-20 transfer for a withdrawal row that has been committed
    to the database. Never resubmit a row with a hash or reserved nonce.
    """
    if withdrawal.transaction_hash or withdrawal.broadcast_nonce is not None:
        return withdrawal

    if withdrawal.paid_status in (
        PaidStatusModelMixin.PAID,
        PaidStatusModelMixin.FAILED,
    ):
        return withdrawal

    if withdrawal.paid_status not in (
        PaidStatusModelMixin.INITIATED,
        PaidStatusModelMixin.PENDING,
    ):
        return withdrawal

    network = withdrawal.network
    w3 = _get_w3_for_network(network)
    amount = Decimal(withdrawal.amount)

    contract = w3.eth.contract(
        abi=contract_abi,
        address=Web3.to_checksum_address(
            settings.WEB3_BASE_RSC_ADDRESS
            if network == "BASE"
            else RSC_CONTRACT_ADDRESS
        ),
    )

    HotWalletService(transfer=execute_erc20_transfer).send(
        w3=w3,
        sender=settings.WEB3_WALLET_ADDRESS,
        private_key=_get_private_key_for_transfer(),
        contract=contract,
        to_address=withdrawal.to_address,
        amount=amount,
        network=network,
        withdrawal_id=withdrawal.id,
    )
    withdrawal.refresh_from_db()
    return withdrawal


def dispatch_withdrawal_broadcast(withdrawal_id):
    """Schedule on-chain broadcast after the current DB transaction commits."""
    from reputation.tasks import broadcast_withdrawal

    transaction.on_commit(lambda: broadcast_withdrawal.delay(withdrawal_id))


class PendingWithdrawal:
    def __init__(self, withdrawal, balance_record_id, amount, network="ETHEREUM"):
        self.withdrawal = withdrawal
        self.balance_record_id = balance_record_id
        self.amount = amount
        self.network = network

    def complete_token_transfer(self):
        broadcast_withdrawal_transfer(self.withdrawal)


def evaluate_transaction_hash(transaction_hash, network="ETHEREUM"):
    if not transaction_hash:
        return PaidStatusModelMixin.PENDING, None

    paid_date = None
    paid_status = PaidStatusModelMixin.PENDING
    try:
        timeout = 5 * 1  # 5 second timeout
        w3_instance = (
            web3_provider.ethereum if network == "ETHEREUM" else web3_provider.base
        )
        transaction_receipt = w3_instance.eth.wait_for_transaction_receipt(
            transaction_hash, timeout=timeout
        )
        if transaction_receipt["status"] == 0:
            paid_status = "FAILED"
        elif transaction_receipt["status"] == 1:
            paid_status = "PAID"
            paid_date = datetime.now()
    except Exception:
        logger.exception("Error evaluating transaction hash=%s", transaction_hash)

    return paid_status, paid_date


def check_pending_withdrawal():
    """
    Re-enqueue stuck broadcasts and promote PENDING withdrawals based on receipts.
    """
    from reputation.services.withdrawal_recovery_service import (
        WithdrawalRecoveryService,
    )

    WithdrawalRecoveryService().check_pending()


def check_hotwallet():
    """
    Alerts admins if the hotwallet is low on eth or RSC on either network
    """
    messages = []
    should_send = False

    # Check Ethereum network
    eth_rsc_balance = get_hotwallet_rsc_balance("ETHEREUM")
    eth_balance_wei = web3_provider.ethereum.eth.get_balance(
        settings.WEB3_WALLET_ADDRESS
    )
    eth_balance_eth = eth_balance_wei / (10**18)

    if eth_rsc_balance <= 50000:
        messages.append(
            f"RSC is running low in the Ethereum hotwallet: {eth_rsc_balance:,}"
        )
        should_send = True

    if eth_balance_eth < 0.08:
        messages.append(
            f"ETH is running low in the Ethereum hotwallet: {eth_balance_eth:,}"
        )
        should_send = True

    # Check Base network
    base_rsc_balance = get_hotwallet_rsc_balance("BASE")
    base_balance_wei = web3_provider.base.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
    base_balance_eth = base_balance_wei / (10**18)

    if base_rsc_balance <= 50000:
        messages.append(
            f"RSC is running low in the Base hotwallet: {base_rsc_balance:,}"
        )
        should_send = True

    if base_balance_eth < 0.001:
        messages.append(
            f"ETH is running low in the Base hotwallet: {base_balance_eth:,}"
        )
        should_send = True

    if should_send:
        context = {
            "action": {"message": "\n\n".join(messages)},
            "subject": "Hotwallet Balance Alert",
        }
        EmailService().send_transactional_email(
            ["pat@researchhub.com", "tyler@researchhub.com", "dev@researchhub.com"],
            "Hotwallet Balance Alert",
            context,
            template="general_email_message",
        )


def get_hotwallet_rsc_balance(network="ETHEREUM"):
    w3_instance = web3_provider.base if network == "BASE" else web3_provider.ethereum
    token_address = (
        RSC_CONTRACT_ADDRESS
        if network == "ETHEREUM"
        else settings.WEB3_BASE_RSC_ADDRESS
    )

    contract = w3_instance.eth.contract(
        abi=contract_abi, address=Web3.to_checksum_address(token_address)
    )
    rsc_balance_wei = contract.functions.balanceOf(settings.WEB3_WALLET_ADDRESS).call()
    decimals = contract.functions.decimals().call()
    rsc_balance_eth = rsc_balance_wei / (10**decimals)
    return rsc_balance_eth


def gwei_to_eth(gwei):
    return gwei * 0.000000001


def get_gas_price_wei(network="ETHEREUM"):
    """Get gas price in wei for the specified network."""
    if network == "BASE":
        res = requests.get(
            f"https://api.etherscan.io/v2/api"
            f"?chainid=8453"
            f"&module=proxy"
            f"&action=eth_gasPrice"
            f"&apikey={settings.ETHERSCAN_API_KEY}",
            timeout=10,
        )
        json = res.json()
        gas_price_wei = int(json.get("result", "0x0"), 16)
    else:
        res = requests.get(
            f"https://api.etherscan.io/v2/api?chainid=1"
            f"&module=gastracker"
            f"&action=gasoracle"
            f"&apikey={settings.ETHERSCAN_API_KEY}",
            timeout=10,
        )
        json = res.json()
        gas_price_gwei = json.get("result", {}).get("SafeGasPrice", 40)
        gas_price_wei = int(float(gas_price_gwei) * 10**9)

    return gas_price_wei


def calculate_transaction_fee(network="ETHEREUM"):
    """Calculate the transaction fee based on the network."""
    gas_price_wei = get_gas_price_wei(network)
    gas_price_gwei = gas_price_wei / 10**9

    gas_limit = 120000.0

    gas_fee_in_eth = gwei_to_eth(float(gas_price_gwei) * gas_limit)
    rsc = RscExchangeRate.eth_to_rsc(gas_fee_in_eth)
    return decimal.Decimal(str(math.ceil(rsc * 100) / 100))
