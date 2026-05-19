from django.apps import AppConfig


class PurchaseConfig(AppConfig):
    name = "purchase"

    def ready(self):
        import purchase.signals
