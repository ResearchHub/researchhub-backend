from datetime import datetime

import pytz
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from jwt import encode
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from hub.models import Hub
from invite.models import NoteInvitation
from invite.serializers import DynamicNoteInvitationSerializer
from note.models import Note, NoteContent
from note.serializers import NoteContentSerializer, NoteSerializer
from researchhub.pagination import MediumPageLimitPagination
from researchhub.settings import (
    CKEDITOR_CLOUD_ACCESS_KEY,
    CKEDITOR_CLOUD_ENVIRONMENT_ID,
    TESTING,
)
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
from researchhub_document.related_models.constants.document_type import NOTE
from user.models import Organization, User
from utils.http import RequestMethods


class NoteViewSet(ModelViewSet):
    ordering = "-created_date"
    queryset = Note.objects.filter(unified_document__is_removed=False)
    permission_classes = [IsAuthenticated, HasAccessPermission]
    serializer_class = NoteSerializer
    pagination_class = MediumPageLimitPagination

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        organization_slug = data.get("organization_slug", None)
        title = data.get("title", "")
        grouping = data.get("grouping", WORKSPACE)

        if organization_slug:
            organization = Organization.objects.get(slug=organization_slug)
            created_by = user
            if not (
                organization.org_has_admin_user(user, content_user=False)
                or organization.org_has_member_user(user, content_user=False)
            ):
                return Response({"data": "Invalid permissions"}, status=403)
        else:
            created_by = user
            organization = user.organization

        unified_doc = self._create_unified_doc(request)
        self._create_permission(created_by, organization, unified_doc, grouping)
        note = Note.objects.create(
            created_by=created_by,
            organization=organization,
            unified_document=unified_doc,
            title=title,
        )
        serializer = self.serializer_class(note)
        data = serializer.data
        note.notify_note_created()
        return Response(data, status=200)

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

        serializer = self.get_serializer(note, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(note, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            note._prefetched_objects_cache = {}

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

        recipient = User.objects.filter(email=recipient_email)
        if recipient.exists():
            recipient = recipient.first()
        else:
            recipient = None

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
            .exclude(expiration_date__lt=datetime.now(pytz.utc))
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
        invites.update(expiration_date=datetime.now(pytz.utc))
        return Response({"data": f"Invite removed for {recipient_email}"}, status=200)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_note_by_key(self, request, pk=None):
        invite = NoteInvitation.objects.get(key=pk)
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
        note.invited_users.update(expiration_date=datetime.now(pytz.utc))

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


class NoteContentViewSet(ModelViewSet):
    ordering = "-created_date"
    queryset = NoteContent.objects.all()
    permission_classes = [IsAuthenticated, HasEditingPermission]
    serializer_class = NoteContentSerializer

    def get_object(self):
        request_method = self.request.method
        if request_method == RequestMethods.POST:
            queryset = Note.objects.all()
        else:
            queryset = self.filter_queryset(self.get_queryset())

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
            "Expected view %s to be called with a URL keyword argument "
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            "attribute on the view correctly."
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        if request_method != RequestMethods.POST:
            self.check_object_permissions(self.request, obj.note)
        else:
            self.check_object_permissions(self.request, obj)

        return obj

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        full_src = data.get("full_src", "")
        note_id = data.get("note", None)
        plain_text = data.get("plain_text", None)
        self.kwargs["pk"] = note_id

        note = self.get_object()
        note_content = NoteContent.objects.create(note=note, plain_text=plain_text)
        file_name, full_src_file = self._create_src_content_file(
            note_content, full_src, user
        )

        if not TESTING:
            note_content.src.save(file_name, full_src_file)

        serializer = self.serializer_class(note_content)
        data = serializer.data
        return Response(data, status=200)

    def _create_src_content_file(self, note_content, full_src, user):
        file_name = f"NOTE-CONTENT-{note_content.id}--USER-{user.id}.txt"
        full_src_file = ContentFile(full_src.encode())
        return file_name, full_src_file


@api_view([RequestMethods.POST])
@permission_classes([AllowAny])
def ckeditor_webhook_document_removed(request):
    document = request.data["payload"]["document"]
    try:
        document_data = document["data"]
    except KeyError:
        return HttpResponse("Missing document data.")

    note_id = document["id"].split("-")[-1]
    note = Note.objects.get(id=note_id)
    note_content = NoteContent.objects.create(note=note, plain_text=None)
    file_name = f"NOTE-CONTENT-{note_content.id}--WEBHOOK.txt"
    full_src_file = ContentFile(document_data.encode())
    note_content.src.save(file_name, full_src_file)

    serializer = NoteContentSerializer(note_content)
    data = serializer.data
    return Response(data, status=200)


@api_view([RequestMethods.GET])
@permission_classes([IsAuthenticated])
def ckeditor_token(request):
    user = request.user
    author_profile = user.author_profile

    payload = {
        "aud": CKEDITOR_CLOUD_ENVIRONMENT_ID,
        "iat": datetime.utcnow(),
        "sub": str(author_profile.id),
        "user": {
            "email": user.email,
            "name": f"{user.first_name} {user.last_name}",
            "avatar": getattr(author_profile.profile_image, "url", ""),
        },
        "auth": {"collaboration": {"*": {"role": "writer"}}},
    }

    encoded = encode(payload, CKEDITOR_CLOUD_ACCESS_KEY, algorithm="HS256")
    return HttpResponse(encoded)
