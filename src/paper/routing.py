from django.urls import re_path

from paper import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/(?P<paper_submission_id>[-\w]+)/paper_submission/$",
        consumers.PaperSubmissionConsumer.as_asgi(),
    )
]
