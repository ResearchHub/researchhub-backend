import json

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from .models import Notification
from .serializers import NotificationSerializer
from user.models import User


class NotificationConsumer(WebsocketConsumer):
    def connect(self):
        kwargs = self.scope['url_route']['kwargs']
        if 'user' in self.scope:
            user = self.scope['user']
        else:
            user_id = kwargs['user_id']
            user = User.objects.get(id=user_id)

        if user.is_anonymous:
            self.close(code=401)
        else:
            self.user = user
            room = f'notification_{user.id}'
            self.room_group_name = room

            async_to_sync(self.channel_layer.group_add)(
                self.room_group_name,
                self.channel_name
            )
            self.accept(subprotocol='Token')

    def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, 'room_group_name'):
            return
        else:
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name,
                self.channel_name
            )

    def send_notification(self, event):
        # Send message to webSocket (Frontend)
        notification_type = event['notification_type']
        notification_id = event['id']
        notification = Notification.objects.get(id=notification_id)
        serialized_data = NotificationSerializer(notification).data
        data = {
            'notification_type': notification_type,
            'data': serialized_data
        }
        self.send(text_data=json.dumps(data))
