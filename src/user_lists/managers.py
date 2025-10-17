from django.db import models


class ListQuerySet(models.QuerySet):
    """
    Custom queries for List objects.
    """

    def for_user(self, user):
        """
        This is the default way lists should be queried.
        """

        return self.filter(created_by=user, is_removed=False)


class ListManager(models.Manager.from_queryset(ListQuerySet)):
    """
    Extends the default manager to add custom queries. Ex: List.objects.for_user(user)
    """

    pass
