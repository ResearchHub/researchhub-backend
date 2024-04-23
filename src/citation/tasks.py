from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from citation.serializers import CitationEntrySerializer
from citation.utils import get_citation_entry_from_pdf
from researchhub.celery import QUEUE_CERMINE, app


@app.task(queue=QUEUE_CERMINE)
def handle_creating_citation_entry(
    path, filename, user_id, organization_id, project_id, retry=0
):
    if retry > 3:
        return

    entry, dupe = get_citation_entry_from_pdf(
        path, filename, user_id, organization_id, project_id
    )

    created = CitationEntrySerializer(entry).data

    room = f"citation_entry_{user_id}"
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        room,
        {
            "dupe_citation": dupe,
            "created_citation": created,
            "type": "send_upload_complete",
        },
    )
