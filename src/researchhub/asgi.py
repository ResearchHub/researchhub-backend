# flake8: noqa

"""
ASGI entrypoint. Configures Django and then runs the application
defined in the ASGI_APPLICATION setting.
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()


from django.conf import settings

import note.routing
import notification.routing
import user.routing
from notification.token_auth import TokenAuthMiddlewareStack
from researchhub.settings import CELERY_WORKER

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "researchhub.settings")

# Wrap Django ASGI application with Elastic APM middleware.
# This is necessary to capture transaction data for performance monitoring.
# The standard Elastic APM middleware for Django does not support ASGI applications.
if hasattr(settings, "ELASTIC_APM") and not CELERY_WORKER:
    from elasticapm.contrib.asgi import ASGITracingMiddleware

    django_asgi_app = ASGITracingMiddleware(django_asgi_app)

routing = {}

routing["http"] = django_asgi_app

if not CELERY_WORKER:
    routing["websocket"] = AllowedHostsOriginValidator(
        TokenAuthMiddlewareStack(
            URLRouter(
                [
                    *note.routing.websocket_urlpatterns,
                    *notification.routing.websocket_urlpatterns,
                    *user.routing.websocket_urlpatterns,
                ]
            )
        )
    )

application = ProtocolTypeRouter(routing)
application = ProtocolTypeRouter(routing)
