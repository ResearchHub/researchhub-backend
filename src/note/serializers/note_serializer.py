from datetime import datetime

import pytz
from django.db.models import Q
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from note.models import Note, NoteContent
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.constants import (
    ADMIN,
    EDITOR,
    MEMBER,
    PRIVATE,
    SHARED,
    WORKSPACE,
)
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import (
    DynamicOrganizationSerializer,
    DynamicUserSerializer,
    OrganizationSerializer,
)


class NoteContentSerializer(ModelSerializer):
    src = SerializerMethodField()

    class Meta:
        model = NoteContent
        fields = "__all__"

    def get_src(self, note_content):
        src = note_content.src
        if src:
            byte_string = note_content.src.read()
            data = byte_string.decode("utf-8")
            return data
        return None


class DynamicNoteContentSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = NoteContent
        fields = "__all__"


class NoteSerializer(ModelSerializer):
    access = SerializerMethodField()
    hypothesis = SerializerMethodField()
    latest_version = NoteContentSerializer()
    organization = OrganizationSerializer()
    post = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta:
        model = Note
        fields = "__all__"
        read_only_fields = ["unified_document"]

    def get_access(self, note):
        permissions = note.permissions

        is_workspace = permissions.filter(
            organization__isnull=False, access_type=ADMIN
        ).exists()

        is_private = (
            permissions.filter(
                Q(access_type__in=[ADMIN, MEMBER, EDITOR]) & Q(user__isnull=False)
            ).count()
            <= 1
        )

        has_invited_users = note.invited_users.filter(
            accepted=False, expiration_date__gt=datetime.now(pytz.utc)
        ).exists()

        if is_workspace:
            return WORKSPACE
        elif is_private and not has_invited_users:
            return PRIVATE
        else:
            return SHARED

    def get_hypothesis(self, note):
        from hypothesis.serializers import DynamicHypothesisSerializer

        if not hasattr(note, "hypothesis"):
            return None

        context = {
            "hyp_dhs_get_authors": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "user",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                ]
            },
        }
        serializer = DynamicHypothesisSerializer(
            note.hypothesis,
            context=context,
            _include_fields=[
                "authors",
                "hubs",
                "id",
                "slug",
            ],
        )
        return serializer.data

    def get_post(self, note):
        from researchhub_document.serializers import DynamicPostSerializer

        if not hasattr(note, "post"):
            return None

        context = {
            "doc_dps_get_authors": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "user",
                ]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                ]
            },
        }
        serializer = DynamicPostSerializer(
            note.post,
            context=context,
            _include_fields=[
                "authors",
                "doi",
                "hubs",
                "id",
                "slug",
            ],
        )
        return serializer.data

    def get_unified_document(self, note):
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document, _include_fields=["id", "is_removed"]
        )
        return serializer.data


class DynamicNoteSerializer(DynamicModelFieldSerializer):
    access = SerializerMethodField()
    created_by = SerializerMethodField()
    hypothesis = SerializerMethodField()
    latest_version = SerializerMethodField()
    notes = SerializerMethodField()
    organization = SerializerMethodField()
    post = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta:
        model = Note
        fields = "__all__"

    def get_access(self, note):
        permissions = note.permissions

        is_workspace = permissions.filter(
            organization__isnull=False, access_type=ADMIN
        ).exists()

        is_private = (
            permissions.filter(
                Q(access_type__in=[ADMIN, MEMBER, EDITOR]) & Q(user__isnull=False)
            ).count()
            <= 1
        )

        has_invited_users = note.invited_users.filter(
            accepted=False, expiration_date__gt=datetime.now(pytz.utc)
        ).exists()

        if is_workspace:
            return WORKSPACE
        elif is_private and not has_invited_users:
            return PRIVATE
        else:
            return SHARED

    def get_created_by(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_created_by", {})
        serializer = DynamicUserSerializer(
            note.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_hypothesis(self, note):
        from hypothesis.serializers import DynamicHypothesisSerializer

        context = self.context
        _context_fields = context.get("nte_dns_get_hypothesis", {})
        serializer = DynamicHypothesisSerializer(
            note.hypothesis, context=context, **_context_fields
        )
        return serializer.data

    def get_latest_version(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_latest_version", {})
        serializer = DynamicNoteContentSerializer(
            note.latest_version, context=context, **_context_fields
        )
        return serializer.data

    def get_notes(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_notes", {})
        serializer = DynamicNoteContentSerializer(
            note.notes, context=context, **_context_fields
        )
        return serializer.data

    def get_organization(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_organization", {})
        serializer = DynamicOrganizationSerializer(
            note.organization, context=context, **_context_fields
        )
        return serializer.data

    def get_post(self, note):
        from researchhub_document.serializers import DynamicPostSerializer

        context = self.context
        _context_fields = context.get("nte_dns_get_post", {})
        serializer = DynamicPostSerializer(
            note.post, context=context, **_context_fields
        )
        return serializer.data

    def get_unified_document(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document, context=context, **_context_fields
        )
        return serializer.data
