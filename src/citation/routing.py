from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/citation_entry/(?P<user_id>\w+)/$',
        consumers.CitationEntryConsumer.as_asgi()
    )
]
