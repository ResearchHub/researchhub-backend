import json
import os
from researchhub.settings import (
    BASE_DIR,
    WEB3_ETH_SUPPLIER_ADDRESS,
    WEB3_ERC20_SUPPLIER_ADDRESS
)
from ethereum.apps import w3, DEFAULT_ADDRESS
from ethereum.lib import TOKENS


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


research_coin_contract = ContractComposer(
    TOKENS['rsc']['contract_address'],
    'MiniMeToken.json'
).contract

eth_supplier_contract = ContractComposer(
    WEB3_ETH_SUPPLIER_ADDRESS,
    'ETHSupplier.json'
).contract

erc20_supplier_contract = ContractComposer(
    WEB3_ERC20_SUPPLIER_ADDRESS,
    'ERC20Supplier.json'
).contract


def request_top_up_eth():
    return eth_supplier_contract.functions.withdraw(DEFAULT_ADDRESS)


def request_top_up_erc20():
    return erc20_supplier_contract.functions.withdraw(
        erc20_supplier_contract.address,
        DEFAULT_ADDRESS
    )
