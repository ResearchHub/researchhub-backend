import json
import os
from researchhub.settings import BASE_DIR
from ethereum.apps import w3
from ethereum.lib import TOKENS
from ethereum.utils import get_address, get_erc20_balance


class ContractComposer:
    def __init__(self, address, abi_filename):
        self.address = address
        self.abi_filename = abi_filename
        self.set_abi()
        self.set_contract()

    def set_abi(self):
        path = os.path.join(
            BASE_DIR,
            'static',
            'ethereum',
            self.abi_filename
        )
        with open(path, 'r') as file:
            data = json.load(file)
        self.abi = data['abi']

    def set_contract(self):
        self.contract = w3.eth.contract(address=self.address, abi=self.abi)


def get_eth_balance(account):
    if account is None:
        account = get_address()
    return w3.eth.getBalance(account)


research_coin_contract = ContractComposer(
    TOKENS['rhc']['contract_address'],
    'MiniMeToken.json'
).contract


def get_rhc_balance(account):
    if account is None:
        account = get_address()
    return get_erc20_balance(research_coin_contract, account)
