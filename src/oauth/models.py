from django.db import models
from django.utils import timezone

class Throttle(models.Model):
    throttle_key = models.CharField(max_length=255, default=None, null=True, blank=True, db_index=True)
    locked = models.BooleanField(default=False)
    captchas_completed = models.IntegerField(default=0)
    ident = models.CharField(max_length=255, default=None, null=True, blank=True, db_index=True)

    user = models.ForeignKey(
        'user.User',
        null=True,
        blank=True,
        related_name='throttles',
        on_delete=models.SET_NULL
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Locked: {}, ident: {}, User: {}'.format(self.locked, self.ident, self.user)


