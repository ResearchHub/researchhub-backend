import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import Notification
from .serializers import NotificationSerializer
from user.models import User


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        kwargs = self.scope['url_route']['kwargs']
        if 'user' in self.scope:
            print('--------- user in scope ---------')
            user = self.scope['user']
        else:
            user_id = kwargs['user_id']
            user = await database_sync_to_async(User.objects.get)(id=user_id)

        if user.is_anonymous:
            await self.close(code=401)
        else:
            self.user = user
            room = f'notification_{user.id}_{user.first_name}_{user.last_name}'
            self.room_group_name = room
            print(self.room_group_name)
            print(self.channel_name)

            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()

    async def disconnect(self, close_code):
        print(close_code)
        if close_code == 401 or not hasattr(self, 'room_group_name'):
            return
        else:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Can Ignore - Backend testing
    async def receive(self, text_data, **kwargs):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message
            }
        )

    # Can Ignore - Backend testing
    async def chat_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'message': message
        }))

    @database_sync_to_async
    async def send_notification(self, event):
        notification_type = event['notification_type']
        notification_id = event['id']
        notification = Notification.objects.get(id=notification_id)
        serialized_data = NotificationSerializer(notification).data
        # Send message to WebSocket (Frontend)
        data = {
            'notification_type': notification_type,
            'data': serialized_data
        }
        await self.send(text_data=json.dumps(data))
