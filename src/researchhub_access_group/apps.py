from django.apps import AppConfig


class ResearchhubAccessGroupConfig(AppConfig):
    name = 'researchhub_access_group'

    def ready(self):
        import researchhub_access_group.signals
