import json

from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer

from paper.models import Paper, PaperSubmission
from paper.serializers import DynamicPaperSerializer, PaperSubmissionSerializer


class PaperSubmissionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]
        user_id = kwargs["user_id"]

        room = f"{user_id}_paper_submissions"
        self.room_group_name = room

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept(subprotocol="Token")

    async def receive(self, text_data=None, bytes_data=None):
        # TODO: Sanitize data?
        data = json.loads(text_data)
        submission_id = data["paper_submission_id"]
        submission = PaperSubmission.objects.get(id=submission_id)
        submission.status_read = True
        submission.save()
        self.notify_paper_submission_status({"id": submission_id})

    async def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, "room_group_name"):
            return
        else:
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )

    def _get_duplicate_paper_data(self, ids):
        papers = Paper.objects.filter(id__in=ids)
        serializer = DynamicPaperSerializer(
            papers, many=True, _include_fields=["doi", "id", "title"]
        )
        return serializer.data

    async def notify_paper_submission_status(self, event):
        # Send message to webSocket (Frontend)
        extra_metadata = {}
        submission_id = event["id"]

        if "duplicate_ids" in event:
            duplicate_ids = event["duplicate_ids"]
            extra_metadata["duplicate_papers"] = self._get_duplicate_paper_data(
                duplicate_ids
            )

        submission = PaperSubmission.objects.get(id=submission_id)
        serialized_data = PaperSubmissionSerializer(submission).data
        current_paper_data = DynamicPaperSerializer(
            submission.paper, _include_fields=["id", "paper_title"]
        ).data

        if "id" not in current_paper_data:
            current_paper_data["id"] = ""

        data = {
            "data": serialized_data,
            "current_paper": current_paper_data,
            **extra_metadata,
        }
        await self.send(text_data=json.dumps(data))
