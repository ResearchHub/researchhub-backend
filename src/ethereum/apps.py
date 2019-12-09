import os
from django.apps import AppConfig
from web3 import Web3

from researchhub.settings import (
    BASE_DIR,
    WEB3_PROVIDER_URL,
    WEB3_KEYSTORE_FILE,
    WEB3_KEYSTORE_PASSWORD
)


class EthereumConfig(AppConfig):
    name = 'ethereum'


class ConfigureWeb3:
    def __init__(self):
        self.w3 = self.configure_Web3()
        self.DEFAULT_PRIVATE_KEY = self.get_default_private_key()
        self.DEFAULT_ADDRESS = self.get_default_address()

    def configure_Web3(self):
        w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))
        if (w3.isConnected()):
            print('web3 connected to', w3.clientVersion)
            return w3

    def get_default_private_key(self):
        path = os.path.join(
            BASE_DIR,
            'config',
            WEB3_KEYSTORE_FILE
        )
        with open(path) as keyfile:
            encrypted_key = keyfile.read()
            return self.w3.eth.account.decrypt(
                encrypted_key,
                WEB3_KEYSTORE_PASSWORD
            )

    def get_default_address(self):
        return self.w3.eth.account.from_key(self.DEFAULT_PRIVATE_KEY).address


web3_config = ConfigureWeb3()

w3 = web3_config.w3
DEFAULT_PRIVATE_KEY = web3_config.DEFAULT_PRIVATE_KEY
DEFAULT_ADDRESS = web3_config.DEFAULT_ADDRESS
