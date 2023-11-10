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


@app.task(queue=QUEUE_CERMINE)
def add_pdf_to_citation(citation_id, file_key):
    CitationEntry = apps.get_model("citation.CitationEntry")

    try:
        citation = CitationEntry.objects.get(id=citation_id)
        pdf = default_storage.open(file_key)
        filename = slugify(file_key.split("/")[-1])
        citation.attachment.save(filename, pdf)
    except Exception as e:
        log_error(e)
