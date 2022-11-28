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

import note.routing
import notification.routing
import user.routing
from notification.token_auth import TokenAuthMiddlewareStack
from researchhub.settings import CELERY_WORKER, DEVELOPMENT

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "researchhub.settings")

routing = {}

if not CELERY_WORKER:
    routing["http"] = django_asgi_app

if CELERY_WORKER or DEVELOPMENT:
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
