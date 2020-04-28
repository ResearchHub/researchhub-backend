from django.apps import AppConfig


class DiscussionConfig(AppConfig):
    name = 'discussion'

    def ready(self):
        import discussion.signals