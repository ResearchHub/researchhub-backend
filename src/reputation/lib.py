import json
import logging
import os
from datetime import datetime, timezone

from web3 import Web3

import ethereum.lib
import ethereum.utils
from ethereum.lib import RSC_CONTRACT_ADDRESS, execute_erc20_transfer, get_private_key
from mailing_list.lib import base_email_context
from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from researchhub.settings import (
    ASYNC_SERVICE_HOST,
    WEB3_KEYSTORE_ADDRESS,
    WEB3_SHARED_SECRET,
    w3,
)
from utils.http import RequestMethods, http_request
from utils.message import send_email_message
from utils.sentry import log_error

WITHDRAWAL_MINIMUM = int(os.environ.get("WITHDRAWAL_MINIMUM", 100))
WITHDRAWAL_PER_TWO_WEEKS = 100000

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

try:
    PRIVATE_KEY = get_private_key()
except Exception as e:
    print(e)
    PRIVATE_KEY = None
    log_error(e)


class PendingWithdrawal:
    def __init__(self, withdrawal, balance_record_id, amount):
        self.withdrawal = withdrawal
        self.balance_record_id = balance_record_id
        self.amount = amount

    def complete_token_transfer(self):
        self.withdrawal.set_paid_pending()
        self.token_payout = (
            self._calculate_tokens_and_update_withdrawal_amount()
        )  # noqa
        self._request_transfer("RSC")

    def _calculate_tokens_and_update_withdrawal_amount(self):
        (
            token_payout,
            blank,
        ) = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
            "RSC", self.amount
        )
        self.withdrawal.amount = self.amount
        self.withdrawal.save()
        return token_payout

    def _request_transfer(self, token):
        url = ASYNC_SERVICE_HOST + "/ethereum/erc20transfer"
        message = {
            "balance_record": self.balance_record_id,
            "withdrawal": self.withdrawal.id,
            "token": token,
            "to": self.withdrawal.to_address,
            "amount": self.token_payout,
        }

        contract = w3.eth.contract(
            abi=contract_abi, address=Web3.to_checksum_address(RSC_CONTRACT_ADDRESS)
        )
        amount = int(self.amount)
        paid = False
        to = self.withdrawal.to_address
        tx_hash = execute_erc20_transfer(
            w3, WEB3_KEYSTORE_ADDRESS, PRIVATE_KEY, contract, to, amount
        )
        self.withdrawal.transaction_hash = tx_hash
        self.withdrawal.save()


def evaluate_transaction_hash(
    transaction_hash,
):
    paid_date = None
    paid_status = "FAILED"
    try:
        timeout = 5 * 1  # 5 second timeout
        transaction_receipt = w3.eth.waitForTransactionReceipt(
            transaction_hash, timeout=timeout
        )
        if transaction_receipt["status"] == 0:
            paid_status = "FAILED"
        elif transaction_receipt["status"] == 1:
            paid_status = "PAID"
            paid_date = datetime.now()
    except Exception as e:
        print(e)
        log_error(e)

    return paid_status, paid_date


def check_pending_withdrawal():
    """
    Checks pending withdrawal and sees if it's completed
    """
    pending_withdrawals = Withdrawal.objects.filter(
        paid_status=PaidStatusModelMixin.PENDING
    )
    for withdrawal in pending_withdrawals:
        paid_status, paid_date = evaluate_transaction_hash(withdrawal.transaction_hash)
        withdrawal.paid_status = paid_status
        withdrawal.paid_date = paid_date
        withdrawal.save()


def check_hotwallet():
    """
    Alerts admins if the hotwallet is low on eth or RSC
    """

    contract = w3.eth.contract(
        abi=contract_abi, address=Web3.to_checksum_address(RSC_CONTRACT_ADDRESS)
    )
    rsc_balance_wei = contract.functions.balanceOf(WEB3_KEYSTORE_ADDRESS).call()
    decimals = contract.functions.decimals().call()
    rsc_balance_eth = rsc_balance_wei / (10**decimals)
    eth_balance_wei = w3.eth.getBalance(WEB3_KEYSTORE_ADDRESS)
    eth_balanace_eth = eth_balance_wei / (10**18)
    send_email = False
    outer_subject = "RSC is running low in the hotwallet"

    if rsc_balance_eth <= 300000:
        outer_subject = "RSC is running low in the hotwallet"
        send_email = True

    if eth_balanace_eth < 0.08:
        outer_subject = "ETH is running low in the hotwallet"
        send_email = True

    if send_email:
        context = {**base_email_context}
        context["action"] = {
            "message": "RSC: {:,}\n\nETH: {:,}".format(
                rsc_balance_eth, eth_balanace_eth
            )
        }
        context["subject"] = outer_subject
        send_email_message(
            ["patricklu@researchhub.com", "pat@researchhub.com"],
            "general_email_message.txt",
            outer_subject,
            context,
            html_template="general_email_message.html",
        )
