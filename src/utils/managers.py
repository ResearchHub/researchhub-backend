from django.db import models
from django.db.models.query import QuerySet

"""Adapted from https://github.com/jazzband/django-model-utils"""


class SoftDeletableQuerySetMixin:
    """QuerySet for SoftDeletableModel. Instead of removing instance sets
    its `is_removed` field to True.
    """

    def delete(self):
        """Soft delete objects from queryset (set their `is_removed`
        field to True)
        """
        self.update(is_removed=True)


class SoftDeletableQuerySet(SoftDeletableQuerySetMixin, QuerySet):
    pass


class SoftDeletableManagerMixin:
    """Manager that limits the queryset by default to show only not removed
    instances of model.
    """
    _queryset_class = SoftDeletableQuerySet

    def get_queryset(self):
        """Return queryset limited to not deleted entries."""
        kwargs = {'model': self.model, 'using': self._db}
        if hasattr(self, '_hints'):
            kwargs['hints'] = self._hints

        return self._queryset_class(**kwargs).filter(is_removed=False)


class SoftDeletableManager(SoftDeletableManagerMixin, models.Manager):
    pass
