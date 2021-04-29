from django.db import models

from user.related_models.user_model import User


class Follow(models.Model):
    user = models.ForeignKey(
        User,
        related_name='following',
        on_delete=models.CASCADE,
    )
    followee = models.ForeignKey(
        User,
        related_name='followers',
        on_delete=models.CASCADE,
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'followee')

    def __str__(self):
        return f'Follower: {str(self.user)}, Followee: {str(self.followee)}'
