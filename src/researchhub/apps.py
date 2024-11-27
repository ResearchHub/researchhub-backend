from django.apps import AppConfig
from health_check.plugins import plugin_dir


class ResearchhubConfig(AppConfig):
    name = "researchhub"

    def ready(self):
        from researchhub.health_check import GitHashBackend

        plugin_dir.register(GitHashBackend)
