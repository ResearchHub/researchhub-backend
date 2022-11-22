import json

from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from utils.parsers import json_serial


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if "user" not in self.scope:
            self.close(code=401)
            raise StopConsumer()

        user = self.scope["user"]
        if user.is_anonymous:
            self.close(code=401)
            raise StopConsumer()
        else:
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
        notification_type = event["notification_type"]
        event_data = event["data"]
        data = {"notification_type": notification_type, "data": event_data}
        await self.send(text_data=json.dumps(data, default=json_serial))
