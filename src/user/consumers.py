import json

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from hub.serializers import DynamicHubSerializer
from paper.models import Paper, PaperSubmission
from paper.serializers import DynamicPaperSerializer, PaperSubmissionSerializer


@database_sync_to_async
def get_paper_submission(submission_id):
    return PaperSubmission.objects.get(id=submission_id)


@database_sync_to_async
def filter_papers(paper_ids):
    return Paper.objects.filter(id__in=paper_ids)


@database_sync_to_async
def get_paper_from_submission(submission):
    return submission.paper


@database_sync_to_async
def get_hubs_from_unified_document(unified_document):
    return unified_document.hubs


@database_sync_to_async
def serialize_hubs(hubs):
    return DynamicHubSerializer(
        hubs, many=True, _include_fields=["id", "name", "slug"]
    ).data


@database_sync_to_async
def get_unified_document_from_paper(paper):
    return paper.unified_document


@database_sync_to_async
def update_submission(submission, data):
    for key, value in data.items():
        setattr(submission, key, value)
    submission.save()


@database_sync_to_async
def get_dynamic_paper_serializer(data, **kwargs):
    serializer = DynamicPaperSerializer(data, **kwargs)
    return serializer.data


class PaperSubmissionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if "user" not in self.scope:
            self.close(code=401)
            raise StopConsumer()

        user = self.scope["user"]
        if user.is_anonymous:
            self.close(code=401)
            raise StopConsumer()
        else:
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
        submission = await get_paper_submission(submission_id)
        await update_submission(submission, {"status_read": True})
        await self.notify_paper_submission_status({"id": submission_id})

    async def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, "room_group_name"):
            return
        else:
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )
        raise StopConsumer()

    async def _get_duplicate_paper_data(self, ids):
        papers = await filter_papers(ids)
        data = await get_dynamic_paper_serializer(
            papers, many=True, _include_fields=["doi", "id", "title"]
        )
        return data

    async def notify_paper_submission_status(self, event):
        # Send message to webSocket (Frontend)
        extra_metadata = {}
        submission_id = event["id"]

        if "duplicate_ids" in event:
            duplicate_ids = event["duplicate_ids"]
            extra_metadata["duplicate_papers"] = await self._get_duplicate_paper_data(
                duplicate_ids
            )

        submission = await get_paper_submission(submission_id)
        # Not entirely sure if the paper submission serializer requires async support
        serialized_data = PaperSubmissionSerializer(submission).data
        paper = await get_paper_from_submission(submission)

        hubs = []
        unified_document = None

        if paper:
            unified_document = await get_unified_document_from_paper(paper)
            hubs = await get_hubs_from_unified_document(unified_document)

        current_paper_data = DynamicPaperSerializer(
            paper, _include_fields=["id", "paper_title", "slug"]
        ).data

        current_hub_data = await serialize_hubs(hubs)

        if "id" not in current_paper_data:
            current_paper_data["id"] = ""

        data = {
            "data": serialized_data,
            "current_paper": current_paper_data,
            "current_hubs": current_hub_data,
            **extra_metadata,
        }
        await self.send(text_data=json.dumps(data))
