from datetime import UTC, datetime

from django.core.files.storage import default_storage
from django.db.models import Q
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.serializers import SimpleHubSerializer
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
from researchhub_document.models import ResearchhubPost
from researchhub_document.registered_report_note_metadata import (
    get_registered_report_prefill_metadata,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.models import Author
from user.serializers import (
    AuthorSerializer,
    DynamicOrganizationSerializer,
    DynamicUserSerializer,
    OrganizationSerializer,
)


class NoteContentSerializer(ModelSerializer):
    src = SerializerMethodField()

    class Meta:
        model = NoteContent
        fields = "__all__"
        # Server-owned lineage and attribution: set by the create paths,
        # never client-writable (PUT/PATCH must not forge them).
        read_only_fields = ["created_by", "created_via", "note", "parent_version"]

    def get_src(self, note_content):
        if note_content.json:  # If JSON exists, don't return src
            return None

        src = note_content.src
        if not src:
            return None
        with src.open() as file:
            return file.read().decode("utf-8")


class DynamicNoteContentSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = NoteContent
        fields = "__all__"


class NoteSerializer(ModelSerializer):
    access = SerializerMethodField()
    latest_version = NoteContentSerializer()
    organization = OrganizationSerializer()
    post = SerializerMethodField()
    registered_report_prefill = SerializerMethodField()
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
            accepted=False, expiration_date__gt=datetime.now(UTC)
        ).exists()

        if is_workspace:
            return WORKSPACE
        elif is_private and not has_invited_users:
            return PRIVATE
        else:
            return SHARED

    def get_post(self, note):
        from researchhub_document.serializers import DynamicPostSerializer

        if not hasattr(note, "post"):
            return None

        context = {
            # Propagate the request so DynamicPostSerializer can resolve the
            # viewer and avoid redacting private posts they are allowed to see.
            "request": self.context.get("request"),
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
            "doc_dps_get_unified_document": {"_include_fields": ["fundraise", "grant"]},
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "doc_duds_get_grant": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "currency",
                    "organization",
                    "description",
                    "start_date",
                    "end_date",
                    "created_by",
                    "contacts",
                    "applications",
                    "application_visibility",
                ]
            },
            "pch_dgs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
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
                "image_url",
                "slug",
                "status",
                "document_type",
                "unified_document",
            ],
        )
        return serializer.data

    def get_registered_report_prefill(self, note) -> dict[str, object] | None:
        """Return registered report draft metadata for notebook editing."""
        return build_registered_report_prefill(note, self.context)

    def get_unified_document(self, note):
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document, _include_fields=["id", "is_removed"]
        )
        return serializer.data


class DynamicNoteSerializer(DynamicModelFieldSerializer):
    access = SerializerMethodField()
    created_by = SerializerMethodField()
    latest_version = SerializerMethodField()
    notes = SerializerMethodField()
    organization = SerializerMethodField()
    post = SerializerMethodField()
    registered_report_prefill = SerializerMethodField()
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
            accepted=False, expiration_date__gt=datetime.now(UTC)
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

        if not hasattr(note, "post"):
            return None

        context = {
            # Propagate the request so DynamicPostSerializer can resolve the
            # viewer and avoid redacting private posts they are allowed to see.
            "request": self.context.get("request"),
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
            "doc_dps_get_unified_document": {"_include_fields": ["fundraise", "grant"]},
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "doc_duds_get_grant": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "currency",
                    "organization",
                    "description",
                    "start_date",
                    "end_date",
                    "created_by",
                    "contacts",
                    "applications",
                    "application_visibility",
                ]
            },
            "pch_dgs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
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
                "image_url",
                "slug",
                "status",
                "document_type",
                "unified_document",
            ],
        )
        return serializer.data

    def get_registered_report_prefill(self, note) -> dict[str, object] | None:
        """Return registered report draft metadata for notebook editing."""
        return build_registered_report_prefill(note, self.context)

    def get_unified_document(self, note):
        context = self.context
        _context_fields = context.get("nte_dns_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document, context=context, **_context_fields
        )
        return serializer.data


def build_registered_report_prefill(
    note: Note, context: dict
) -> dict[str, object] | None:
    """Build editable registered report defaults from stored note data."""
    if note.document_type != REGISTERED_REPORT or hasattr(note, "post"):
        return None

    latest_version = getattr(note, "latest_version", None)
    metadata = {}
    if latest_version is not None:
        metadata = get_registered_report_prefill_metadata(latest_version.json)

    author_ids = get_registered_report_author_ids(metadata)
    authors = get_registered_report_authors(author_ids)
    if not authors and note.created_by is not None:
        authors = [note.created_by.author_profile]
        author_ids = [note.created_by.author_profile.id]
    hubs = note.unified_document.hubs.all()
    hub_ids = list(hubs.values_list("id", flat=True))
    hub_data = SimpleHubSerializer(hubs, context=context, many=True).data
    image, preview_img = _get_registered_report_images(metadata)
    if image:
        preview_img = default_storage.url(image)

    return {
        "author_ids": author_ids,
        "authors": AuthorSerializer(
            authors,
            context=context,
            many=True,
        ).data,
        "image": image,
        "preview_img": preview_img,
        "proposal_id": metadata.get("proposal_id"),
        "hub_ids": hub_ids,
        "hubs": hub_data,
    }


def _get_registered_report_images(
    metadata: dict[str, object],
) -> tuple[str | None, str | None]:
    """Return draft images, filling missing values from the live proposal."""
    image = metadata.get("image")
    preview_img = metadata.get("preview_img")
    image = image if isinstance(image, str) else None
    preview_img = preview_img if isinstance(preview_img, str) else None
    if image is not None and preview_img is not None:
        return image, preview_img

    proposal_id = metadata.get("proposal_id")
    if not isinstance(proposal_id, int):
        return image, preview_img

    proposal = (
        ResearchhubPost.objects.filter(
            document_type=PREREGISTRATION,
            id=proposal_id,
        )
        .only("image", "preview_img")
        .first()
    )
    if proposal is None:
        return image, preview_img

    return (
        image if image is not None else proposal.image,
        preview_img if preview_img is not None else proposal.preview_img,
    )


def get_registered_report_author_ids(metadata: dict[str, object]) -> list[int]:
    """Return valid author ids from registered report metadata."""
    raw_author_ids = metadata.get("author_ids")
    if not isinstance(raw_author_ids, list):
        return []
    return [author_id for author_id in raw_author_ids if isinstance(author_id, int)]


def get_registered_report_authors(author_ids: list[int]) -> list[Author]:
    """Return authors in the same order as registered report metadata."""
    authors_by_id = Author.objects.in_bulk(author_ids)
    return [
        authors_by_id[author_id]
        for author_id in author_ids
        if author_id in authors_by_id
    ]
