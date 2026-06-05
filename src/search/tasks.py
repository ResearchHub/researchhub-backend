import logging
from collections.abc import Iterable, Iterator
from itertools import islice

from paper.models import Paper
from researchhub.celery import QUEUE_ELASTIC_SEARCH, app
from researchhub_document.models import ResearchhubPost
from search.documents.base import BaseDocument
from search.documents.paper import PaperDocument
from search.documents.person import PersonDocument
from search.documents.post import PostDocument
from search.documents.user import UserDocument
from user.models import Author, User

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_ELASTIC_SEARCH, ignore_result=True)
def update_user_related_documents(user_id: int, batch_size: int = 500) -> None:
    """
    Update search documents related to the given user.
    """

    user = User.objects.filter(id=user_id).first()
    if user is None:
        logger.info("Skipping index updates due to user_id=%s not found", user_id)
        return

    # Update papers
    _update_document(
        PaperDocument(),
        Paper.objects.filter(uploaded_by=user).iterator(chunk_size=batch_size),
        batch_size=batch_size,
    )

    # Update posts
    _update_document(
        PostDocument(),
        ResearchhubPost.objects.filter(created_by=user)
        .select_related("unified_document")
        .iterator(chunk_size=batch_size),
        batch_size=batch_size,
    )

    # Update users
    _update_document(
        UserDocument(),
        [user],
        batch_size=batch_size,
    )

    # Update authors
    author = Author.objects.filter(user=user).select_related("user").first()
    if author is not None:
        _update_document(
            PersonDocument(),
            [author],
            batch_size=batch_size,
        )


def _iter_batches(
    iterable: Iterable[object], batch_size: int
) -> Iterator[list[object]]:
    iterator = iter(iterable)
    while batch := list(islice(iterator, batch_size)):
        yield batch


def _update_document(
    document: BaseDocument, objects: Iterable[object], batch_size: int = 500
) -> None:
    for batch in _iter_batches(objects, batch_size):
        document.update(batch, action="index", raise_on_error=False)
