from django.apps import AppConfig


class ResearchhubCaseConfig(AppConfig):
    name = 'researchhub_case'

    def ready(self):
        import researchhub_case.signals
