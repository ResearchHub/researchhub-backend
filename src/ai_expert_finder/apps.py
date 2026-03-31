"""
AI Expert Finder Django app.

If the database still has migrations recorded as app ``research_ai``, run once before
``migrate`` (PostgreSQL)::

    UPDATE django_migrations SET app = 'ai_expert_finder' WHERE app = 'research_ai';
    UPDATE django_content_type SET app_label = 'ai_expert_finder' WHERE app_label = 'research_ai';
"""

from django.apps import AppConfig


class AIExpertFinderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_expert_finder"
    verbose_name = "AI Expert Finder"

    def ready(self):
        import ai_expert_finder.signals  # noqa: F401
