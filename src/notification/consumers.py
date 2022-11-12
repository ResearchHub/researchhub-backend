import json

from channels.db import database_sync_to_async
from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from user.models import User
from utils.parsers import json_serial


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]
        if "user" in self.scope:
            user = self.scope["user"]
        else:
            user_id = kwargs["user_id"]
            user = database_sync_to_async(User.objects.get(id=user_id))

        if user.is_anonymous:
            self.close(code=401)
        else:
            self.user = user
            room = f"notification_{user.id}"
            self.room_group_name = room

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept(subprotocol="Token")

    async def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, "room_group_name"):
            return
        else:
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )
        raise StopConsumer()

    async def send_notification(self, event):
        try:
            notification_type = event["notification_type"]
            event_data = event["data"]
            data = {"notification_type": notification_type, "data": event_data}
            await self.send(text_data=json.dumps(data, default=json_serial))
        except Exception as e:
            print("WEBSOCKET NOTIFICATION ERROR", e)
        finally:
            print("SENDING NOTIFICATION NOW!!!!!!!")
