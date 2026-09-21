from celery.signals import worker_process_shutdown
from django.apps import AppConfig
from django.conf import settings

from research_ai.services.tracing_service import flush_tracing, initialize_tracing


class ResearchAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "research_ai"
    verbose_name = "Research AI"

    def __init__(self, app_name, app_module):
        super().__init__(app_name, app_module)
        # Patch provider SDKs before Django imports models and provider clients.
        initialize_tracing(
            project_id=settings.BRAINTRUST_PROJECT_ID,
            project_name=settings.BRAINTRUST_PROJECT_NAME,
        )

    def ready(self):
        import research_ai.signals  # noqa: F401

        worker_process_shutdown.connect(flush_tracing, weak=False)
