from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/(?P<organization_slug>[-\w]+)/notebook/$',
        consumers.NoteConsumer.as_asgi()
     )
]
