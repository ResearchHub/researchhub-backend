from django.apps import AppConfig


class EthereumConfig(AppConfig):
    name = 'ethereum'

    def ready(self):
        import os
        self._os = os
        self.configureWeb3()
        self.setDefaultPrivateKey()

    def configureWeb3(self):
        from researchhub.settings import WEB3_INFURA_PROJECT_ID

        # Set the environment variable before w3 import so it can auto connect
        self._os.environ['WEB3_INFURA_PROJECT_ID'] = WEB3_INFURA_PROJECT_ID

        from web3.auto.infura import w3
        if (w3.isConnected()):
            self.w3 = w3
            print('web3 connected to', w3.clientVersion)

    def setDefaultPrivateKey(self):
        from researchhub.settings import BASE_DIR
        from config import wallet
        path = self._os.path.join(
            BASE_DIR,
            'config',
            wallet.KEYSTORE_FILE
        )
        with open(path) as keyfile:
            encrypted_key = keyfile.read()
            self.DEFAULT_PRIVATE_KEY = self.w3.eth.account.decrypt(
                encrypted_key,
                wallet.KEYSTORE_PASSWORD
            )
