from django.urls import re_path

from user import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/(?P<user_id>[-\w]+)/paper_submissions/$",
        consumers.PaperSubmissionConsumer.as_asgi(),
    )
]
