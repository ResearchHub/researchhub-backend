import json

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from .models import Notification
from .serializers import NotificationSerializer
from user.models import User


class NotificationConsumer(WebsocketConsumer):
    def connect(self):
        kwargs = self.scope['url_route']['kwargs']
        if 'user' in kwargs:
            print('--------- user in scope ---------')
            user = kwargs['user']
        else:
            user_id = kwargs['user_id']
            user = User.objects.get(id=user_id)
        self.user = user
        room = f'notification_{user.id}_{user.first_name}_{user.last_name}'
        self.room_group_name = room
        print(self.room_group_name)
        print(self.channel_name)

        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )
        self.accept()

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(
            self.room_group_name,
            self.channel_name
        )

    # Can Ignore - Backend testing
    def receive(self, text_data, **kwargs):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        # Send message to room group
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message
            }
        )

    # Can Ignore - Backend testing
    def chat_message(self, event):
        message = event['message']
        self.send(text_data=json.dumps({
            'message': message
        }))

    def send_notification(self, event):
        notification_type = event['notification_type']
        notification_id = event['id']
        notification = Notification.objects.get(id=notification_id)
        serialized_data = NotificationSerializer(notification).data
        # Send message to WebSocket (Frontend)
        data = {
            'notification_type': notification_type,
            'data': serialized_data
        }
        self.send(text_data=json.dumps(data))
