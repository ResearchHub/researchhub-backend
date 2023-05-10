from asgiref.sync import async_to_sync
from django.core.files.storage import default_storage
from channels.layers import get_channel_layer

from citation.utils import get_citation_entry_from_pdf
from citation.serializers import CitationEntrySerializer
from researchhub.celery import (
    QUEUE_CERMINE,
    app,
)


@app.task(queue=QUEUE_CERMINE)
def handle_creating_citation_entry(path, user_id, organization_id, project_id):
    pdf = default_storage.open(path)
    entry = get_citation_entry_from_pdf(pdf, user_id, organization_id, project_id)
    created = CitationEntrySerializer(entry).data

    room = f"citation_entry_{user_id}"
    channel_layer = get_channel_layer()
    print(room)
    print(channel_layer)
    async_to_sync(channel_layer.group_send)(
        room,
        {
            "created_citation": created
        },
    )
