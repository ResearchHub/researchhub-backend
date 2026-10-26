import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class ResearchhubConfig(AppConfig):
    name = "researchhub"

    def ready(self):
        if settings.USE_DEBUG_TOOLBAR:
            logger.info("Using Debug Toolbar")

        from utils.web3_utils import web3_provider

        _ = web3_provider.ethereum
        _ = web3_provider.base
