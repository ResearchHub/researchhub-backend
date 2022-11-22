import json

from channels.db import database_sync_to_async
from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from user.models import Organization


@database_sync_to_async
def check_org_has_user(user, organization_slug):
    organization = Organization.objects.filter(slug=organization_slug)
    if organization.exists():
        organization = organization.first()
    else:
        return False
    return organization.org_has_user(user)


class NoteConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if "user" not in self.scope:
            self.close(code=401)
            raise StopConsumer()

        user = self.scope["user"]
        if user.is_anonymous:
            self.close(code=401)
            raise StopConsumer()
        else:
            kwargs = self.scope["url_route"]["kwargs"]
            organization_slug = kwargs["organization_slug"]

            org_has_user = await check_org_has_user(user, organization_slug)
            if not org_has_user:
                self.close(code=401)
                raise StopConsumer()

            room = f"{organization_slug}_notebook"
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

    async def send_note_notification(self, event):
        data = event["data"]
        await self.send(text_data=json.dumps(data))
