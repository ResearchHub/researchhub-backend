import json
import os
from researchhub.settings import BASE_DIR
from ethereum.apps import w3


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
    '0x7D50101BbFa12f4A1B4e6de0Dd58Ad36dE150D55',
    'MiniMeToken.json'
).contract
