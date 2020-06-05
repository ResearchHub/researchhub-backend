import logging
import os

import smart_open
from django.apps import AppConfig
from web3 import Web3

from researchhub.settings import (
    DEVELOPMENT,
    BASE_DIR,
    CONFIG_BASE_DIR,
    WEB3_PROVIDER_URL,
    WEB3_KEYSTORE_FILE,
    WEB3_KEYSTORE_PASSWORD
)
from utils.aws import get_s3_url


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
        return None

    def get_keystore_path(self):
        if DEVELOPMENT:
            try:
                local_path = os.path.join(
                    BASE_DIR,
                    CONFIG_BASE_DIR,
                    WEB3_KEYSTORE_FILE
                )
                return local_path
            except Exception as e:
                logging.warning(f'Could not find keystore path. {e}')
                return None
        try:
            bucket = 'keystore-researchcoin/'
            return get_s3_url(bucket, WEB3_KEYSTORE_FILE, with_credentials=True)  # noqa: E501
        except Exception as e:
            logging.warning(f'Could not find keystore path. {e}')
            return None

    def get_default_private_key(self):
        try:
            path = self.get_keystore_path()
            with smart_open.open(path) as keyfile:
                encrypted_key = keyfile.read()
            return self.w3.eth.account.decrypt(
                encrypted_key,
                WEB3_KEYSTORE_PASSWORD
            )
        except Exception as e:
            logging.warning(f'Could not retrieve private key. {e}')
            return None

    def get_default_address(self):
        try:
            return self.w3.eth.account.from_key(self.DEFAULT_PRIVATE_KEY).address  # noqa: E501
        except Exception as e:
            logging.warning(f'Could not retrieve default address. {e}')
            return None


web3_config = ConfigureWeb3()

w3 = web3_config.w3
DEFAULT_PRIVATE_KEY = web3_config.DEFAULT_PRIVATE_KEY
DEFAULT_ADDRESS = web3_config.DEFAULT_ADDRESS
