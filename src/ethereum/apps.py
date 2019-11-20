from django.apps import AppConfig


class EthereumConfig(AppConfig):
    name = 'ethereum'

    def ready(self):
        self.configureWeb3()

    def configureWeb3(self):
        import os
        from researchhub.settings import WEB3_INFURA_PROJECT_ID

        # Set the environment variable before w3 import so it can auto connect
        os.environ['WEB3_INFURA_PROJECT_ID'] = WEB3_INFURA_PROJECT_ID

        from web3.auto.infura import w3
        if (w3.isConnected()):
            print('web3 connected to', w3.clientVersion)
