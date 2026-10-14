from django.apps import AppConfig


class ResearchhubConfig(AppConfig):
    name = "researchhub"

    def ready(self):
        from utils.web3_utils import web3_provider

        _ = web3_provider.ethereum
        _ = web3_provider.base
