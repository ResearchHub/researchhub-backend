from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/notebook/notes/(?P<note_id>[0-9]+)/chats/(?P<conversation_id>[0-9]+)/$",
        consumers.NotebookChatConsumer.as_asgi(),
    ),
    re_path(
        r"ws/assistant/chats/(?P<conversation_id>[0-9]+)/$",
        consumers.AssistantChatConsumer.as_asgi(),
    ),
]
