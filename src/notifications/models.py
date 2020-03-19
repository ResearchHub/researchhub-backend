from django.db import models

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from paper.models import Paper
from user.models import User, Action

# Create your models here.

class Notification(models.Model):
    read = models.BooleanField(default=False)

    paper = models.ForeignKey(
        Paper,
        related_name='notifications',
        on_delete=models.CASCADE
    )

    # The user that should receive the notification
    receiver = models.ForeignKey(
        User,
        related_name='receiver_notifications',
        on_delete=models.CASCADE,
    )

    # The user that created the notifcation, e.g the user that created the comment, etc
    creator = models.ForeignKey(
        User,
        related_name='creator_notifications',
        on_delete=models.CASCADE
    )
    action = models.ForeignKey(
        Action,
        related_name='notifications',
        on_delete=models.CASCADE
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def send_notification(self):
        user = self.receiver
        room_group_name = f'notification_{user.id}_{user.first_name}_{user.last_name}'
        print(room_group_name)
        notification_type = self.action.content_type.app_label
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'send_notification',
                'notification_type': notification_type,
                'id': self.id,
            }
        )
