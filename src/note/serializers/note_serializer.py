from datetime import UTC, datetime

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from rest_framework.serializers import (
    ModelSerializer,
    PrimaryKeyRelatedField,
    SerializerMethodField,
    ValidationError,
)

from hub.models import Hub
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from note.models import GrantSettings, Note, NoteContent, PreregistrationSettings
from note.services.grant_selection_service import (
    GrantSelectionError,
    selectable_grants,
    validate_selection,
)
from note.services.note_draft_service import save_note_draft_details
from organizations.models import NonprofitOrg
from organizations.serializers import NonprofitOrgSerializer
from purchase.models import Grant
from purchase.serializers.grant_serializer import DynamicGrantSerializer
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
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.models import Author, User
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
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


class GrantSettingsSerializer(ModelSerializer):
    """Draft grant form values held by a notebook note."""

    contact_ids = PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        required=False,
        source="contacts",
    )
    # Contacts are picked by name, so the form cannot redraw them from ids alone.
    contacts = DynamicUserSerializer(
        many=True,
        read_only=True,
        _include_fields=["first_name", "id", "last_name"],
    )

    class Meta:
        model = GrantSettings
        fields = [
            "amount",
            "application_visibility",
            "contact_ids",
            "contacts",
            "currency",
            "description",
            "end_date",
            "organization",
        ]


class PreregistrationSettingsSerializer(ModelSerializer):
    """Draft preregistration form values held by a notebook note."""

    # The nonprofit is shown by name and EIN, so the form cannot redraw it from
    # an id alone.
    nonprofit_details = NonprofitOrgSerializer(read_only=True, source="nonprofit")
    nonprofit_id = PrimaryKeyRelatedField(
        allow_null=True,
        queryset=NonprofitOrg.objects.all(),
        required=False,
        source="nonprofit",
    )

    class Meta:
        model = PreregistrationSettings
        fields = [
            "duration_days",
            "goal_amount",
            "goal_currency",
            "is_public",
            "nonprofit_details",
            "nonprofit_id",
        ]


class NoteSerializer(ModelSerializer):
    access = SerializerMethodField()
    author_ids = PrimaryKeyRelatedField(
        many=True,
        queryset=Author.objects.all(),
        required=False,
        write_only=True,
    )
    # A byline needs names and faces, not the reputation, wallet, and editor
    # lookups AuthorSerializer runs per author.
    authors = DynamicAuthorSerializer(
        many=True,
        read_only=True,
        source="ordered_authors",
        _include_fields=["first_name", "id", "last_name", "profile_image", "user"],
    )
    grant_settings = GrantSettingsSerializer(required=False)
    hub_ids = PrimaryKeyRelatedField(
        many=True,
        queryset=Hub.objects.all(),
        required=False,
        write_only=True,
    )
    # Topic chips need names, not the editor permission groups SimpleHubSerializer
    # queries and serializes per hub.
    hubs = DynamicHubSerializer(
        many=True,
        read_only=True,
        source="unified_document.hubs",
        _include_fields=["id", "name", "slug"],
    )
    # Version lineage and workspace are owned by the content signal and the
    # view's organization_slug resolution, never by a note payload.
    latest_version = NoteContentSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    post = SerializerMethodField()
    preregistration_settings = PreregistrationSettingsSerializer(required=False)
    registered_report_prefill = SerializerMethodField()
    selected_grant = PrimaryKeyRelatedField(
        allow_null=True,
        queryset=Grant.objects.none(),
        required=False,
    )
    # The RFP card shows the grant, not its id, and the funder's visibility rule
    # decides whether the applicant may still choose a public proposal.
    selected_grant_details = DynamicGrantSerializer(
        read_only=True,
        source="selected_grant",
        _include_fields=[
            "amount",
            "application_visibility",
            "id",
            "image_url",
            "organization",
            "short_title",
        ],
    )
    unified_document = SerializerMethodField()

    class Meta:
        model = Note
        fields = "__all__"
        # The creator is set from the request, never from a note payload.
        read_only_fields = ["created_by"]

    def get_fields(self) -> dict:
        """Return fields with writable grants restricted to the requester."""
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and hasattr(self, "initial_data"):
            fields["selected_grant"].queryset = selectable_grants(request.user)
        return fields

    def validate(self, attrs: dict) -> dict:
        """Validate the selected grant and funding forms against the note's type."""
        document_type = attrs.get(
            "document_type", getattr(self.instance, "document_type", None)
        )
        self._validate_funding_details(attrs, document_type)

        selection_requires_validation = "selected_grant" in attrs or (
            self.instance is not None
            and self.instance.selected_grant_id is not None
            and document_type != self.instance.document_type
        )
        if not selection_requires_validation:
            return attrs

        selected_grant = attrs.get(
            "selected_grant", getattr(self.instance, "selected_grant", None)
        )
        try:
            validate_selection(document_type=document_type, grant=selected_grant)
        except GrantSelectionError as exc:
            raise ValidationError({"selected_grant": str(exc)}) from exc
        return attrs

    def _validate_funding_details(
        self, attrs: dict, document_type: str | None
    ) -> None:
        """Reject a funding form the resulting document type does not use."""
        if "grant_settings" in attrs and document_type != GRANT:
            raise ValidationError(
                {"grant_settings": "Only grant notes have grant settings."}
            )
        if "preregistration_settings" in attrs and document_type != PREREGISTRATION:
            raise ValidationError(
                {
                    "preregistration_settings": (
                        "Only preregistration notes have preregistration settings."
                    )
                }
            )

    def create(self, validated_data: dict) -> Note:
        """Create the note and persist the draft Details sent with it."""
        details = self._pop_draft_details(validated_data)
        with transaction.atomic():
            note = super().create(validated_data)
            save_note_draft_details(note, **details)
        return note

    def update(self, note: Note, validated_data: dict) -> Note:
        """Persist the draft Details changes this request carries."""
        details = self._pop_draft_details(validated_data)
        with transaction.atomic():
            if validated_data:
                note = super().update(note, validated_data)
            else:
                # A relationship-only save still has to record when it happened.
                note.save(update_fields=["updated_date"])
            save_note_draft_details(note, **details)
        return note

    def _pop_draft_details(self, validated_data: dict) -> dict:
        """Remove the related draft values, which the draft service writes itself."""
        return {
            "authors": validated_data.pop("author_ids", None),
            "hubs": validated_data.pop("hub_ids", None),
            "grant_settings": validated_data.pop("grant_settings", None),
            "preregistration_settings": validated_data.pop(
                "preregistration_settings", None
            ),
        }

    def to_representation(self, note: Note) -> dict:
        """Return the note, exposing only the funding form its type uses.

        A row kept from an earlier document type stays in the database so
        switching back restores it, but it is not part of the note's contract
        while another type is selected.
        """
        data = super().to_representation(note)
        if note.document_type != GRANT:
            data["grant_settings"] = None
        if note.document_type != PREREGISTRATION:
            data["preregistration_settings"] = None
        return data

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
