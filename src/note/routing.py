from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/(?P<organization_slug>[-\w]+)/notebook/$", consumers.NoteConsumer.as_asgi()
    ),
    re_path(
        r"ws/notebook/notes/(?P<note_id>[0-9]+)/$",
        consumers.NoteVersionConsumer.as_asgi(),
    ),
]
