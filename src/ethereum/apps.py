import logging
import os

import smart_open
from django.apps import AppConfig
from web3 import Web3

from researchhub.settings import (
    BASE_DIR,
    CONFIG_BASE_DIR,
    WEB3_PROVIDER_URL,
    WEB3_KEYSTORE_FILE,
    WEB3_KEYSTORE_PASSWORD
)
from utils.aws import http_to_s3


class EthereumConfig(AppConfig):
    name = 'ethereum'

class ConfigureWeb3:
    def __init__(self):
        self.w3 = self.configure_Web3()
        self.DEFAULT_PRIVATE_KEY = self.get_default_private_key()
        self.DEFAULT_ADDRESS = self.get_default_address()

    def configure_Web3(self):
        w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))
        if w3.isConnected():
            logging.info(f'web3 connected to {w3.clientVersion}')
            return w3
        logging.warning(f'web3 could not connect to {WEB3_PROVIDER_URL}')

    def get_keystore_path(self):
        local_path = os.path.join(
            BASE_DIR,
            CONFIG_BASE_DIR,
            WEB3_KEYSTORE_FILE
        )
        if os.path.exists(local_path):
            return local_path
        # assume keystore is hosted on AWS
        bucket = 'keystore-researchcoin'
        url = f"https://{bucket}.s3-us-west-2.amazonaws.com/{WEB3_KEYSTORE_FILE}"  # noqa E501
        return http_to_s3(url, with_credentials=True)

    def get_default_private_key(self):
        path = self.get_keystore_path()
        with smart_open.open(path) as keyfile:
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
