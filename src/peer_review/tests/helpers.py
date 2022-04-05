from researchhub_document.helpers import (
    create_post,
)
from note.tests.helpers import (
    create_note,
)
from peer_review.models import PeerReviewRequest


def create_peer_review_request(
    requested_by_user,
    organization,
    title='Some random post title',
    body='some text',
):
    note, note_content = create_note(
        created_by=requested_by_user,
        organization=organization,
        title=title,
        body=body,
    )

    review_request = PeerReviewRequest.objects.create(
        requested_by_user=requested_by_user,
        unified_document=note.unified_document,
        doc_version=note_content,
    )

    return review_request
