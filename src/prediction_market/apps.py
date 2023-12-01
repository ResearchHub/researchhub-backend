from django.apps import AppConfig


class PredictionMarketConfig(AppConfig):
    name = "prediction_market"

    def ready(self):
        import prediction_market.signals
