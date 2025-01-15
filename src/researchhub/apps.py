from django.apps import AppConfig
from health_check.plugins import plugin_dir


class ResearchhubConfig(AppConfig):
    name = "researchhub"

    def ready(self):
        from researchhub.health_check import GitHashBackend

        plugin_dir.register(GitHashBackend)

        from utils.web3_utils import web3_provider

        _ = web3_provider.ethereum
        _ = web3_provider.base
