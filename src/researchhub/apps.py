import logging

from django.apps import AppConfig
from django.conf import settings
from health_check.plugins import plugin_dir

logger = logging.getLogger(__name__)


class ResearchhubConfig(AppConfig):
    name = "researchhub"

    def ready(self):
        if settings.USE_DEBUG_TOOLBAR:
            logger.info("Using Debug Toolbar")

        from researchhub.health_check import GitHashBackend

        plugin_dir.register(GitHashBackend)

        from utils.web3_utils import web3_provider

        _ = web3_provider.ethereum
        _ = web3_provider.base
