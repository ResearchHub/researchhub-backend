from django.apps import AppConfig


class ResearchhubDocumentConfig(AppConfig):
    name = 'researchhub_document'

    def ready(self):
        import researchhub_document.signals
