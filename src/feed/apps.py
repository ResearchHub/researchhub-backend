from django.apps import AppConfig


class FeedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "feed"

    def ready(self):
        import feed.signals  # noqa: F401

        # Set up the generic feed management system
        from feed.feed_configs import register_all_feed_entities, setup_m2m_signals

        register_all_feed_entities()
        setup_m2m_signals()
