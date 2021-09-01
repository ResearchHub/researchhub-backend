from django.db import models

from django.contrib.postgres.fields import JSONField
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from user.models import User, Action
from researchhub_document.related_models.researchhub_unified_document_model \
  import ResearchhubUnifiedDocument

# Create your models here.


class Notification(models.Model):
    read = models.BooleanField(default=False)

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        null=True,
        on_delete=models.CASCADE,
        related_name='notifications',
    )

    # The user that should receive the notification
    recipient = models.ForeignKey(
        User,
        related_name='receiver_notifications',
        on_delete=models.CASCADE,
    )

    # The user that created the notifcation, e.g the user created a comment
    action_user = models.ForeignKey(
        User,
        related_name='creator_notifications',
        on_delete=models.CASCADE
    )
    action = models.ForeignKey(
        Action,
        related_name='notifications',
        on_delete=models.CASCADE
    )

    read_date = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def send_notification(self):
        user = self.recipient
        room = f'notification_{user.id}'
        notification_type = self.action.content_type.app_label
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room,
            {
                'type': 'send_notification',
                'notification_type': notification_type,
                'id': self.id,
            }
        )
