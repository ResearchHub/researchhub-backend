from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.apps import apps
from django.core.files.storage import default_storage
from django.utils.text import slugify

from citation.exceptions import GrobidProcessingError
from citation.serializers import CitationEntrySerializer
from citation.utils import get_citation_entry_from_pdf
from researchhub.celery import QUEUE_CERMINE, app
from utils.sentry import log_error


@app.task(queue=QUEUE_CERMINE)
def handle_creating_citation_entry(
    path, filename, user_id, organization_id, project_id, use_grobid=False, retry=0
):
    if retry > 3:
        return
    try:
        entry, dupe = get_citation_entry_from_pdf(
            path, filename, user_id, organization_id, project_id, use_grobid
        )
    except GrobidProcessingError:
        # The Grobid server is probably busy
        # Resend the request after a short delay
        handle_creating_citation_entry.apply_async(
            (
                path,
                filename,
                user_id,
                organization_id,
                project_id,
                use_grobid,
                retry + 1,
            ),
            priority=5,
            countdown=2 * (retry + 1),
        )
        return False

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
