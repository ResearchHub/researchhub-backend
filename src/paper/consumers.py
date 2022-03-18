import json

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from paper.models import PaperSubmission
from paper.serializers import PaperSubmissionSerializer


class PaperSubmissionConsumer(WebsocketConsumer):
    def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]
        paper_submission_id = kwargs["paper_submission_id"]

        room = f"paper_submission_{paper_submission_id}"
        self.room_group_name = room

        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name, self.channel_name
        )
        self.accept(subprotocol="Token")

    def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, "room_group_name"):
            return
        else:
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name, self.channel_name
            )

    def notify_paper_submission_status(self, event):
        # Send message to webSocket (Frontend)
        note_id = event["id"]
        note = PaperSubmission.objects.get(id=note_id)
        serialized_data = PaperSubmissionSerializer(note).data
        data = {
            "data": serialized_data,
        }
        self.send(text_data=json.dumps(data))
