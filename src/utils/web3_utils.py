from django.conf import settings
from web3 import Web3

from utils.sentry import log_error


class Web3Provider:
    _instance = None
    _ethereum = None
    _base = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Web3Provider, cls).__new__(cls)
            cls._initialize_providers()
        return cls._instance

    @classmethod
    def _initialize_providers(cls):
        try:
            if settings.TESTING:
                # Use mock provider for testing
                test_provider = Web3.EthereumTesterProvider()
                cls._ethereum = Web3(test_provider)
                cls._base = Web3(test_provider)
            else:
                cls._ethereum = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))
                cls._base = Web3(Web3.HTTPProvider(settings.WEB3_BASE_PROVIDER_URL))
        except Exception as e:
            log_error(e)
            cls._ethereum = None
            cls._base = None

    @property
    def ethereum(self):
        return self._ethereum

    @property
    def base(self):
        return self._base


web3_provider = Web3Provider()
