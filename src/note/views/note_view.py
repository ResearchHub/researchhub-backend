import logging
from datetime import UTC, datetime

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from hub.models import Hub
from invite.models import NoteInvitation
from invite.serializers import DynamicNoteInvitationSerializer
from invite.services import NoteInvitationExpiredError, NoteInvitationService
from note.models import Note, NoteContent, parse_note_json
from note.serializers import (
    DynamicNoteSerializer,
    NoteContentSerializer,
    NoteSerializer,
)
from researchhub.pagination import MediumPageLimitPagination
from researchhub.settings import TESTING
from researchhub_access_group.constants import (
    ADMIN,
    MEMBER,
    NO_ACCESS,
    PRIVATE,
    WORKSPACE,
)
from researchhub_access_group.models import Permission
from researchhub_access_group.permissions import (
    HasAccessPermission,
    HasAdminPermission,
    HasEditingPermission,
    HasOrgEditingPermission,
    IsOrganizationUser,
)
from researchhub_access_group.serializers import DynamicPermissionSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    REGISTERED_REPORT,
)
from user.models import Organization, User
from utils.prosemirror import BLOCK_EDITOR, parse_document

logger = logging.getLogger(__name__)

# Draft values a published note no longer owns; its post does. `title` stays out
# so a published note can still be renamed.
DRAFT_FIELDS = frozenset(
    {
        "author_ids",
        "fundraise",
        "grant",
        "hub_ids",
        "image",
        "preview_img",
        "selected_grant",
    }
)


class NoteViewSet(ModelViewSet):
    ordering = "-created_date"
    queryset = Note.objects.filter(unified_document__is_removed=False)
    permission_classes = [IsAuthenticated, HasAccessPermission]
    serializer_class = NoteSerializer
    pagination_class = MediumPageLimitPagination

    def get_queryset(self):
        user = self.request.user
        return (
            self.queryset.filter(
                Q(created_by=user)
                | Q(organization__permissions__user=user)
                | Q(unified_document__permissions__user=user)
            )
            .select_related(
                "fundraise_details",
                "fundraise_details__nonprofit",
                "grant_details",
                "post",
                "selected_grant",
                "unified_document",
            )
            .prefetch_related(
                "author_links",
                "grant_details__contacts",
                # The selected grant's image lives on its post.
                "selected_grant__unified_document__posts",
                "unified_document__hubs",
            )
            .distinct()
            .order_by("-created_date")
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def accessible(self, request):
        """
        Endpoint to retrieve all notes that the current user has access to, including
        those associated with organizations they belong to, and those they have explicit
        permissions for (e.g., by invitation).
        The notes are filtered based on the user's access rights and the status of the
        notes (draft or published).
        This endpoint mirrors the behavior and shape of the `get_organization_notes`
        endpoint.
        """
        notes = self._get_accessible_notes(request.user)
        notes = self._filter_accessible_notes(notes, request)
        notes = notes.select_related(
            "organization",
            "unified_document",
        ).prefetch_related(
            "unified_document__permissions",
        )

        page = self.paginate_queryset(notes)
        serializer_data = DynamicNoteSerializer(
            page,
            _include_fields=[
                "access",
                "created_date",
                "document_type",
                "id",
                "organization",
                "title",
                "updated_date",
            ],
            context=self._get_accessible_notes_context(),
            many=True,
        ).data
        return self.get_paginated_response(serializer_data)

    def _get_accessible_notes(self, user) -> QuerySet[Note]:
        return (
            self.queryset.filter(
                (
                    Q(unified_document__permissions__user=user)
                    & ~Q(unified_document__permissions__access_type=NO_ACCESS)
                )
                | (
                    Q(
                        unified_document__permissions__organization__permissions__user=user
                    )
                    & ~Q(unified_document__permissions__access_type=NO_ACCESS)
                )
            )
            .distinct()
            .order_by("-created_date")
        )

    def _filter_accessible_notes(
        self, notes: QuerySet[Note], request
    ) -> QuerySet[Note]:
        status = request.query_params.get("status", "").upper()
        if status == "DRAFT":
            notes = notes.filter(post__isnull=True)
        elif status == "PUBLISHED":
            notes = notes.filter(post__isnull=False)

        note_type = request.query_params.get("type", "").upper()
        if note_type:
            notes = notes.filter(document_type=note_type)

        return notes

    def _get_accessible_notes_context(self) -> dict:
        return {
            "nte_dns_get_organization": {
                "_include_fields": [
                    "cover_image",
                    "id",
                    "name",
                    "slug",
                ]
            }
        }

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        organization_slug = data.get("organization_slug", None)
        grouping = data.get("grouping", WORKSPACE)

        if organization_slug:
            organization = Organization.objects.get(slug=organization_slug)
            if not (
                organization.org_has_admin_user(user, content_user=False)
                or organization.org_has_member_user(user, content_user=False)
            ):
                return Response({"data": "Invalid permissions"}, status=403)
        else:
            organization = user.organization

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            unified_doc = self._create_unified_doc(request)
            self._create_permission(user, organization, unified_doc, grouping)
            note = serializer.save(
                created_by=user,
                organization=organization,
                unified_document=unified_doc,
            )

        note.notify_note_created()
        return Response(serializer.data, status=200)

    def _create_unified_doc(self, request):
        data = request.data
        hubs = Hub.objects.filter(id__in=data.get("hubs", [])).all()
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)
        unified_doc.hubs.add(*hubs)
        unified_doc.save()
        return unified_doc

    def _create_permission(self, creator, organization, unified_document, grouping):
        content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)

        if grouping == WORKSPACE:
            org_access = ADMIN
        elif grouping == PRIVATE:
            org_access = NO_ACCESS
            Permission.objects.create(
                access_type=ADMIN,
                content_type=content_type,
                object_id=unified_document.id,
                user=creator,
            )
        else:
            org_access = ADMIN

        permission = Permission.objects.create(
            access_type=org_access,
            content_type=content_type,
            object_id=unified_document.id,
            organization=organization,
            user=creator,
        )
        return permission

    @action(
        detail=True,
        methods=["post", "delete"],
        permission_classes=[HasOrgEditingPermission | HasEditingPermission],
    )
    def delete(self, request, pk=None):
        note = Note.objects.get(id=pk)
        self.check_object_permissions(self.request, note)

        unified_document = note.unified_document
        unified_document.is_removed = True
        unified_document.save()
        serializer = self.serializer_class(note)
        note.notify_note_deleted()
        return Response(serializer.data, status=200)

    def _create_image_file(self, data, organization, user):
        file_name = f"ORGANIZATION-IMAGE-{organization.id}--USER-{user.id}.txt"
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    def update(self, request, *args, **kwargs):
        user = request.user
        partial = kwargs.pop("partial", False)
        note = self.get_object()
        permissions = note.unified_document.permissions
        is_admin = permissions.has_admin_user(user)
        is_editor = permissions.has_editor_user(user)

        if not (is_admin or is_editor):
            return Response({"data": "Invalid permissions"}, status=403)

        if DRAFT_FIELDS.intersection(request.data) and hasattr(note, "post"):
            return Response(
                {"detail": "Published notes cannot change draft details."},
                status=status.HTTP_409_CONFLICT,
            )

        previous_title = note.title
        serializer = self.get_serializer(note, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(note, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            note._prefetched_objects_cache = {}

        # Autosave patches this route continuously; only a real rename is worth
        # rendering the whole note and broadcasting it to the organization.
        if note.title != previous_title:
            note.notify_note_updated_title()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        return self.delete(request, pk)

    @action(detail=True, methods=["post"], permission_classes=[IsOrganizationUser])
    def invite_user(self, request, pk=None):
        inviter = request.user
        data = request.data
        note = self.get_object()
        access_type = data.get("access_type")
        recipient_email = data.get("email")
        time_to_expire = int(data.get("expire", 1440))

        recipient = User.objects.filter(email=recipient_email).first()

        invite = NoteInvitation.create(
            inviter=inviter,
            recipient=recipient,
            recipient_email=recipient_email,
            note=note,
            invite_type=access_type,
            expiration_time=time_to_expire,
        )
        invite.send_invitation()
        return Response({"data": "Invite sent"}, status=200)

    @action(detail=True, methods=["get"])
    def get_invited_users(self, request, pk=None):
        note = self.get_object()
        invited_users = (
            note.invited_users.filter(accepted=False)
            .exclude(expiration_date__lt=datetime.now(UTC))
            .distinct("recipient_email")
        )
        serializer = DynamicNoteInvitationSerializer(
            invited_users,
            many=True,
            _include_fields=[
                "accepted",
                "created_date",
                "expiration_date",
                "invite_type",
                "recipient_email",
            ],
        )
        return Response(serializer.data, status=200)

    @action(
        detail=True,
        methods=["patch"],
        permission_classes=[IsAuthenticated, IsOrganizationUser],
    )
    def remove_invited_user(self, request, pk=None):
        data = request.data
        note = self.get_object()
        recipient_email = data.get("email")

        invites = NoteInvitation.objects.filter(
            recipient_email=recipient_email,
            note=note,
        )
        invites.update(expiration_date=datetime.now(UTC))
        return Response({"data": f"Invite removed for {recipient_email}"}, status=200)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_note_by_key(self, request, pk=None):
        service = NoteInvitationService()

        try:
            invite = service.get_active_invite(pk)
        except NoteInvitationExpiredError:
            return Response({"data": "Invitation has expired"}, status=403)

        serializer = DynamicNoteInvitationSerializer(
            invite,
            context={
                "inv_dnis_get_inviter": {
                    "_include_fields": [
                        "author_profile",
                    ]
                },
                "inv_dnis_get_note": {
                    "_include_fields": [
                        "created_date",
                        "organization",
                        "title",
                        "id",
                        "latest_version",
                    ]
                },
                "nte_dns_get_latest_version": {
                    "_include_fields": [
                        "created_date",
                        "id",
                        "json",
                        "plain_text",
                        "src",
                    ]
                },
                "nte_dns_get_organization": {
                    "_include_fields": [
                        "slug",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
            },
            _include_fields=[
                "inviter",
                "invite_type",
                "note",
                "recipient_email",
            ],
        )
        return Response(serializer.data, status=200)

    @action(detail=True, methods=["patch"], permission_classes=[HasAdminPermission])
    def update_permissions(self, request, pk=None):
        user = request.user
        data = request.data
        organization_id = data.get("organization")
        user_id = data.get("user")
        access_type = data.get("access_type")
        note = self.get_object()
        unified_document = note.unified_document

        if organization_id:
            permission = unified_document.permissions.get(organization=organization_id)
            if access_type not in (ADMIN, MEMBER):
                return Response({"data": "Invalid access type"}, status=400)
        else:
            permission = unified_document.permissions.get(user=user_id)

        permission.access_type = access_type
        permission.save()
        note.notify_note_updated_permission(user)
        return Response({"data": "Permission updated"}, status=200)

    @action(detail=True, methods=["delete"], permission_classes=[HasAdminPermission])
    def remove_permission(self, request, pk=None):
        data = request.data
        user = request.user
        user_id = data.get("user", None)
        organization_id = data.get("organization", None)

        note = self.get_object()
        permissions = note.permissions
        if user_id:
            permission = permissions.get(user=user_id)
            permission.delete()
        else:
            permission = permissions.get(organization=organization_id)
            permission.access_type = NO_ACCESS
            permission.save()

            # Add user as admin if there is only an org permission
            if permissions.count() == 1:
                content_type = ContentType.objects.get_for_model(
                    ResearchhubUnifiedDocument
                )
                Permission.objects.create(
                    access_type=ADMIN,
                    content_type=content_type,
                    object_id=note.unified_document.id,
                    user=user,
                )

        note.notify_note_updated_permission(user)
        return Response({"data": "Permission removed"}, status=200)

    @action(detail=True, methods=["get"], permission_classes=[HasAccessPermission])
    def get_note_permissions(self, request, pk=None):
        note = self.get_object()
        permissions = note.unified_document.permissions.all()
        context = self._get_note_permissions_context()
        serializer = DynamicPermissionSerializer(
            permissions,
            many=True,
            context=context,
            _include_fields=[
                "access_type",
                "created_date",
                "organization",
                "user",
            ],
        )
        return Response(serializer.data, status=200)

    def _get_note_permissions_context(self):
        context = {
            "rag_dps_get_user": {
                "_include_fields": [
                    "author_profile",
                    "email",
                    "id",
                ]
            },
            "rag_dps_get_organization": {
                "_include_fields": [
                    "cover_image",
                    "id",
                    "name",
                    "member_count",
                    "slug",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[HasAdminPermission | HasOrgEditingPermission],
    )
    def make_private(self, request, pk=None):
        user = request.user
        note = self.get_object()
        note_permissions = note.permissions.all()

        # Remove all non-organization permissions
        note_permissions.filter(organization__isnull=True).delete()

        # Set org permission to no access
        note_permissions.filter(organization__isnull=False).update(
            access_type=NO_ACCESS
        )

        # Updating all note invites
        note.invited_users.update(expiration_date=datetime.now(UTC))

        # Set current user as note admin
        content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=note.unified_document.id,
            user=user,
        )
        serializer = self.serializer_class(note)
        note.notify_note_updated_permission(user)
        return Response(serializer.data, status=200)


class NoteContentViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
):
    # No ListModelMixin: the queryset is unscoped and permissions are only
    # checked per object in get_object, so a list action would expose every note.
    ordering = "-created_date"
    queryset = NoteContent.objects.all()
    permission_classes = [IsAuthenticated, HasEditingPermission]
    serializer_class = NoteContentSerializer

    def get_permissions(self):
        # Reading one version only requires read access to its note (the
        # same gate as the note detail); every mutating action keeps the
        # stricter editing gate.
        if self.action == "retrieve":
            return [IsAuthenticated(), HasAccessPermission()]
        return super().get_permissions()

    def get_queryset(self):
        # Versions of a soft-deleted note read as missing, matching the note
        # detail queryset and the version socket's admission gate.
        return super().get_queryset().filter(note__unified_document__is_removed=False)

    def get_object(self):
        request_method = self.request.method
        if request_method == "POST":
            queryset = Note.objects.all()
        else:
            queryset = self.filter_queryset(self.get_queryset())

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
            f"Expected view {self.__class__.__name__} to be called with a URL keyword "
            f'argument named "{lookup_url_kwarg}". Fix your URL conf, or set the '
            f"`.lookup_field` attribute on the view correctly."
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        if request_method != "POST":
            self.check_object_permissions(self.request, obj.note)
        else:
            self.check_object_permissions(self.request, obj)

        return obj

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        full_src = data.get("full_src", "")
        full_json = data.get("full_json", None)
        note_id = data.get("note", None)
        plain_text = data.get("plain_text", None)
        parent_version_id = data.get("parent_version", None)
        self.kwargs["pk"] = note_id

        note = self.get_object()
        post = getattr(note, "post", None)
        if post is not None and post.document_type == REGISTERED_REPORT:
            return Response(
                {"detail": "Published registered report content cannot be edited."},
                status=status.HTTP_409_CONFLICT,
            )
        parent_version = None
        if parent_version_id is not None:
            parent_version = self._get_parent_version(note, parent_version_id)
            if parent_version is None:
                return Response(
                    {"detail": "parent_version is not a version of this note."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        note_content = NoteContent.objects.create(
            note=note,
            plain_text=plain_text,
            json=full_json,
            created_by=user,
            created_via=NoteContent.CREATED_VIA_EDITOR,
            parent_version=parent_version,
        )
        if full_json is not None:
            self._warn_on_schema_mismatch(note_content)

        # Only save src if full_json is not provided
        if not full_json and full_src:
            file_name, full_src_file = self._create_src_content_file(
                note_content, full_src, user
            )
            if not TESTING:
                note_content.src.save(file_name, full_src_file)

        serializer = self.serializer_class(note_content)
        data = serializer.data
        return Response(data, status=200)

    def _warn_on_schema_mismatch(self, version: NoteContent) -> None:
        """Log stored content the editor schema rejects; never block the save.

        Detection only: rejecting here would turn backend schema lag into
        failed editor saves. The agent note tools require conforming content,
        so this is the early tripwire for drift or API misuse.
        """
        document = parse_note_json(version.json)
        try:
            if document is None:
                raise ValueError("content is not a JSON object")
            parse_document(BLOCK_EDITOR, document)
        except ValueError as exc:
            logger.warning(
                "note %s version %s content does not match the editor schema: %s",
                version.note_id,
                version.id,
                exc,
            )

    def _get_parent_version(self, note, parent_version_id):
        """The referenced version, or ``None`` when it is not one of ``note``'s."""
        try:
            parent_version_id = int(parent_version_id)
        except (TypeError, ValueError):
            return None
        return NoteContent.objects.filter(id=parent_version_id, note=note).first()

    def _create_src_content_file(self, note_content, full_src, user):
        file_name = f"NOTE-CONTENT-{note_content.id}--USER-{user.id}.txt"
        full_src_file = ContentFile(full_src.encode())
        return file_name, full_src_file
