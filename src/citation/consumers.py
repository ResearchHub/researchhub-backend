import json

from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from utils.parsers import json_serial


class CitationEntryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if "user" not in self.scope:
            self.close(code=401)
            raise StopConsumer()

        user = self.scope["user"]
        if user.is_anonymous:
            self.close(code=401)
            raise StopConsumer()
        else:
            room = f"citation_entry_{user.id}"
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

    async def send_upload_complete(self, event):
        created_citation = event["created_citation"]
        data = {"created_citation": created_citation}
        await self.send(text_data=json.dumps(data, default=json_serial))
