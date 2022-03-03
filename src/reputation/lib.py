import json
import logging
import os

import ethereum.utils
import ethereum.lib
from web3 import Web3
from utils.sentry import log_error

from ethereum.lib import get_private_key, RSC_CONTRACT_ADDRESS, execute_erc20_transfer
from researchhub.settings import (
    ASYNC_SERVICE_HOST,
    WEB3_SHARED_SECRET,
    w3,
    WEB3_KEYSTORE_ADDRESS,
)
from utils.http import http_request, RequestMethods
WITHDRAWAL_MINIMUM = 100
WITHDRAWAL_PER_TWO_WEEKS = 100000

contract_abi = [
  {
    "constant": True,
    "inputs": [],
    "name": "name",
    "outputs": [
      {
        "name": "",
        "type": "string"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_spender",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "approve",
    "outputs": [
      {
        "name": "success",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "creationBlock",
    "outputs": [
      {
        "name": "",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "totalSupply",
    "outputs": [
      {
        "name": "",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_from",
        "type": "address"
      },
      {
        "name": "_to",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "transferFrom",
    "outputs": [
      {
        "name": "success",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "decimals",
    "outputs": [
      {
        "name": "",
        "type": "uint8"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_newController",
        "type": "address"
      }
    ],
    "name": "changeController",
    "outputs": [],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [
      {
        "name": "_owner",
        "type": "address"
      },
      {
        "name": "_blockNumber",
        "type": "uint256"
      }
    ],
    "name": "balanceOfAt",
    "outputs": [
      {
        "name": "",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "version",
    "outputs": [
      {
        "name": "",
        "type": "string"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_cloneTokenName",
        "type": "string"
      },
      {
        "name": "_cloneDecimalUnits",
        "type": "uint8"
      },
      {
        "name": "_cloneTokenSymbol",
        "type": "string"
      },
      {
        "name": "_snapshotBlock",
        "type": "uint256"
      },
      {
        "name": "_transfersEnabled",
        "type": "bool"
      }
    ],
    "name": "createCloneToken",
    "outputs": [
      {
        "name": "",
        "type": "address"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [
      {
        "name": "_owner",
        "type": "address"
      }
    ],
    "name": "balanceOf",
    "outputs": [
      {
        "name": "balance",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "parentToken",
    "outputs": [
      {
        "name": "",
        "type": "address"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_owner",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "generateTokens",
    "outputs": [
      {
        "name": "",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "symbol",
    "outputs": [
      {
        "name": "",
        "type": "string"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [
      {
        "name": "_blockNumber",
        "type": "uint256"
      }
    ],
    "name": "totalSupplyAt",
    "outputs": [
      {
        "name": "",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_to",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "transfer",
    "outputs": [
      {
        "name": "success",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "transfersEnabled",
    "outputs": [
      {
        "name": "",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "parentSnapShotBlock",
    "outputs": [
      {
        "name": "",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_spender",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      },
      {
        "name": "_extraData",
        "type": "bytes"
      }
    ],
    "name": "approveAndCall",
    "outputs": [
      {
        "name": "success",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_owner",
        "type": "address"
      },
      {
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "destroyTokens",
    "outputs": [
      {
        "name": "",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [
      {
        "name": "_owner",
        "type": "address"
      },
      {
        "name": "_spender",
        "type": "address"
      }
    ],
    "name": "allowance",
    "outputs": [
      {
        "name": "remaining",
        "type": "uint256"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_token",
        "type": "address"
      }
    ],
    "name": "claimTokens",
    "outputs": [],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "tokenFactory",
    "outputs": [
      {
        "name": "",
        "type": "address"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": False,
    "inputs": [
      {
        "name": "_transfersEnabled",
        "type": "bool"
      }
    ],
    "name": "enableTransfers",
    "outputs": [],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": True,
    "inputs": [],
    "name": "controller",
    "outputs": [
      {
        "name": "",
        "type": "address"
      }
    ],
    "payable": False,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [
      {
        "name": "_tokenFactory",
        "type": "address"
      },
      {
        "name": "_parentToken",
        "type": "address"
      },
      {
        "name": "_parentSnapShotBlock",
        "type": "uint256"
      },
      {
        "name": "_tokenName",
        "type": "string"
      },
      {
        "name": "_decimalUnits",
        "type": "uint8"
      },
      {
        "name": "_tokenSymbol",
        "type": "string"
      },
      {
        "name": "_transfersEnabled",
        "type": "bool"
      }
    ],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "constructor"
  },
  {
    "payable": True,
    "stateMutability": "payable",
    "type": "fallback"
  },
  {
    "anonymous": False,
    "inputs": [
      {
        "indexed": True,
        "name": "_token",
        "type": "address"
      },
      {
        "indexed": True,
        "name": "_controller",
        "type": "address"
      },
      {
        "indexed": False,
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "ClaimedTokens",
    "type": "event"
  },
  {
    "anonymous": False,
    "inputs": [
      {
        "indexed": True,
        "name": "_from",
        "type": "address"
      },
      {
        "indexed": True,
        "name": "_to",
        "type": "address"
      },
      {
        "indexed": False,
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "Transfer",
    "type": "event"
  },
  {
    "anonymous": False,
    "inputs": [
      {
        "indexed": True,
        "name": "_cloneToken",
        "type": "address"
      },
      {
        "indexed": False,
        "name": "_snapshotBlock",
        "type": "uint256"
      }
    ],
    "name": "NewCloneToken",
    "type": "event"
  },
  {
    "anonymous": False,
    "inputs": [
      {
        "indexed": True,
        "name": "_owner",
        "type": "address"
      },
      {
        "indexed": True,
        "name": "_spender",
        "type": "address"
      },
      {
        "indexed": False,
        "name": "_amount",
        "type": "uint256"
      }
    ],
    "name": "Approval",
    "type": "event"
  }
]

try:
    PRIVATE_KEY = get_private_key()
except Exception as e:
    print(e)
    log_error(e)

class PendingWithdrawal:
    def __init__(self, withdrawal, balance_record_id, amount):
        self.withdrawal = withdrawal
        self.balance_record_id = balance_record_id
        self.amount = amount

    def complete_token_transfer(self):
        self.withdrawal.set_paid_pending()
        self.token_payout = self._calculate_tokens_and_update_withdrawal_amount()  # noqa
        self._request_transfer('RSC')

    def _calculate_tokens_and_update_withdrawal_amount(self):
        token_payout, blank = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
            'RSC',
            self.amount
        )
        self.withdrawal.amount = self.amount
        self.withdrawal.save()
        return token_payout

    def _request_transfer(self, token):
        url = ASYNC_SERVICE_HOST + '/ethereum/erc20transfer'
        message = {
            "balance_record": self.balance_record_id,
            "withdrawal": self.withdrawal.id,
            "token": token,
            "to": self.withdrawal.to_address,
            "amount": self.token_payout
        }

        contract = w3.eth.contract(abi=contract_abi, address=Web3.toChecksumAddress(RSC_CONTRACT_ADDRESS))
        amount = int(self.amount)
        paid = False
        to = self.withdrawal.to_address
        tx_hash = execute_erc20_transfer(
            w3,
            WEB3_KEYSTORE_ADDRESS,
            PRIVATE_KEY,
            contract,
            to,
            amount
        )
        self.withdrawal.transaction_hash = tx_hash
        self.withdrawal.save()
