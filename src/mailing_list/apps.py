from django.apps import AppConfig


class MailingListConfig(AppConfig):
    name = "mailing_list"

    def ready(self):
        import mailing_list.signals  # noqa: F401
