from django.core.cache import cache
from django.db import transaction

from user.models import Author, User


class ProfileDeletionService:
    """Soft-delete user and author profiles without losing related records."""

    def __init__(self, cache_backend=None):
        self.cache = cache_backend or cache

    @transaction.atomic
    def delete_user(self, user: User) -> None:
        user = User.all_objects.select_for_update().get(pk=user.pk)
        author = Author.all_objects.select_for_update().filter(user_id=user.pk).first()

        self._mark_user_removed(user)
        if author is not None:
            author.delete()
            self._invalidate_author_caches(author.pk)

    @transaction.atomic
    def delete_author(self, author: Author) -> None:
        author = Author.all_objects.select_for_update().get(pk=author.pk)
        user = None
        if author.user_id is not None:
            user = User.all_objects.select_for_update().get(pk=author.user_id)

        author.delete()
        if user is not None:
            self._mark_user_removed(user)
        self._invalidate_author_caches(author.pk)

    @staticmethod
    def _mark_user_removed(user: User) -> None:
        user.delete()
        user.is_active = False
        user.save(update_fields=["is_active"])

    def _invalidate_author_caches(self, author_id: int) -> None:
        self.cache.delete_many(
            [
                f"author-{author_id}-achievements",
                f"author-{author_id}-overview",
                f"author-{author_id}-profile",
                f"author-{author_id}-publications",
                f"author-{author_id}-summary-stats",
            ]
        )
