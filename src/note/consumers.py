import json

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

from note.models import Note
from note.serializers import NoteSerializer
from user.models import User


class NoteConsumer(WebsocketConsumer):
    def connect(self):
        kwargs = self.scope['url_route']['kwargs']
        organization_slug = kwargs['organization_slug']

        room = f'{organization_slug}_notebook'
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

    def notify_note_created(self, event):
        # Send message to webSocket (Frontend)
        note_id = event['id']
        note = Note.objects.get(id=note_id)
        serialized_data = NoteSerializer(note).data
        data = {
            'type': 'create',
            'data': serialized_data,
        }
        self.send(text_data=json.dumps(data))

    def notify_note_deleted(self, event):
        # Send message to webSocket (Frontend)
        note_id = event['id']
        note = Note.objects.get(id=note_id)
        serialized_data = NoteSerializer(note).data
        data = {
            'type': 'delete',
            'data': serialized_data,
        }
        self.send(text_data=json.dumps(data))

    def notify_note_updated_title(self, event):
        # Send message to webSocket (Frontend)
        note_id = event['id']
        note = Note.objects.get(id=note_id)
        serialized_data = NoteSerializer(note).data
        data = {
            'type': 'update_title',
            'data': serialized_data,
        }
        self.send(text_data=json.dumps(data))

    def notify_note_updated_permission(self, event):
        # Send message to webSocket (Frontend)
        note_id = event['id']
        requester_id = event['requester_id']
        note = Note.objects.get(id=note_id)
        serialized_data = NoteSerializer(note).data
        data = {
            'type': 'update_permission',
            'data': serialized_data,
            'requester': requester_id
        }
        self.send(text_data=json.dumps(data))
