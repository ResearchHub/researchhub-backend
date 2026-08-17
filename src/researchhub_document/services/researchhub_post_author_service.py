from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import F, Prefetch, QuerySet
from django.db.models.signals import m2m_changed

from researchhub_document.models import ResearchhubPost, ResearchhubPostAuthor
from user.models import Author

_ORDERED_AUTHOR_LINKS = "_ordered_author_links"


class ResearchhubPostAuthorValidationError(ValueError):
    """Raised when a post author list is invalid."""


def resolve_authors(author_ids: list[int]) -> list[Author]:
    """Return existing unique authors in the submitted order."""
    if len(author_ids) != len(set(author_ids)):
        raise ResearchhubPostAuthorValidationError("Authors must be unique.")

    authors_by_id = Author.objects.in_bulk(author_ids)
    if len(authors_by_id) != len(author_ids):
        raise ResearchhubPostAuthorValidationError(
            "One or more authors do not exist."
        )
    return [authors_by_id[author_id] for author_id in author_ids]


def list_authors(post: ResearchhubPost) -> list[Author]:
    """Return a post's authors in canonical order."""
    links = getattr(post, _ORDERED_AUTHOR_LINKS, None)
    if links is None:
        database = post._state.db or DEFAULT_DB_ALIAS
        links = _get_ordered_author_links().using(database).filter(
            researchhub_post=post
        )
    return [link.author for link in links]


def build_author_prefetch(
    lookup: str = "researchhubpostauthor_set",
) -> Prefetch:
    """Build a prefetch that supports canonical author reads."""
    return Prefetch(
        lookup,
        queryset=_get_ordered_author_links(),
        to_attr=_ORDERED_AUTHOR_LINKS,
    )


def replace_authors(
    post: ResearchhubPost,
    authors: list[Author],
) -> None:
    """Atomically replace a saved post's authors in the supplied order."""
    if post.pk is None:
        raise ValueError("Post must be saved before replacing authors.")

    database = post._state.db or DEFAULT_DB_ALIAS
    with transaction.atomic(using=database):
        ResearchhubPost.objects.using(database).select_for_update().only("id").get(
            pk=post.pk
        )
        ResearchhubPostAuthor.objects.using(database).filter(
            researchhub_post_id=post.pk
        ).delete()
        ResearchhubPostAuthor.objects.using(database).bulk_create(
            ResearchhubPostAuthor(
                researchhub_post_id=post.pk,
                author_id=author.id,
                position=position,
            )
            for position, author in enumerate(authors, start=1)
        )
        if hasattr(post, _ORDERED_AUTHOR_LINKS):
            delattr(post, _ORDERED_AUTHOR_LINKS)
        getattr(post, "_prefetched_objects_cache", {}).pop("authors", None)
        # bulk_create bypasses Django's M2M signal. Emit only the final event so
        # listeners refresh from the completed replacement instead of observing
        # the transient empty relation created by the delete above.
        m2m_changed.send(
            sender=ResearchhubPost.authors.through,
            instance=post,
            action="post_add",
            reverse=False,
            model=Author,
            pk_set={author.id for author in authors},
            using=database,
        )


def _get_ordered_author_links() -> QuerySet[ResearchhubPostAuthor]:
    """Return post-author links in canonical order."""
    return (
        ResearchhubPostAuthor.objects.filter(author__is_removed=False)
        .select_related("author", "author__user")
        .order_by(
            F("position").asc(nulls_last=True),
            "id",
        )
    )
