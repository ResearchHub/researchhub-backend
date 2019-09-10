from django.apps import AppConfig


class OAuthConfig(AppConfig):
    name = 'oauth'
    verbose_name = 'OAuth'

    def ready(self):
        print('OAuth app is ready')
