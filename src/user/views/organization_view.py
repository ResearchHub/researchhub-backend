from datetime import datetime

import pytz
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import Case, Count, F, Q, Sum, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from citation.models import CitationProject
from invite.models import OrganizationInvitation
from invite.serializers import DynamicOrganizationInvitationSerializer
from note.models import Note, NoteTemplate
from note.serializers import DynamicNoteSerializer, NoteTemplateSerializer
from researchhub.pagination import MediumPageLimitPagination
from researchhub_access_group.constants import ADMIN, MEMBER, NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_access_group.permissions import IsOrganizationAdmin, IsOrganizationUser
from user.models import Organization, User
from user.serializers import (
    DynamicOrganizationSerializer,
    DynamicUserSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(viewsets.ModelViewSet):
    queryset = Organization.objects.all().order_by("-created_date")
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = MediumPageLimitPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "slug",
    ]

    def get_queryset(self):
        user = self.request.user
        organizations = self.queryset.filter(
            permissions__user=user,
        ).distinct()
        return organizations

    def get_object(self, slug=False):
        queryset = self.filter_queryset(self.get_queryset())

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
            "Expected view %s to be called with a URL keyword argument "
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            "attribute on the view correctly."
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        if slug:
            filter_kwargs = {"slug": self.kwargs[lookup_url_kwarg]}
        else:
            filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        self.check_object_permissions(self.request, obj)

        return obj

    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            user = request.user
            data = request.data
            description = data.get("description", "")
            name = data.get("name", None)
            image = data.get("image", None)

            if Organization.objects.filter(name=name).exists():
                return Response({"data": "Name is already in use."}, status=409)

            organization = Organization.objects.create(
                description=description,
                name=name,
            )
            project = CitationProject.objects.create(
                is_public=True,
                slug="my-library",
                project_name="My Library",
                parent_names={"names": ["My Library"], "slugs": ["my-library"]},
                organization=organization,
                created_by=user,
            )
            project.set_creator_as_admin()
            self._create_permissions(user, organization)

            if image:
                file_name, file = self._create_image_file(image, organization, user)
                organization.cover_image.save(file_name, file)

            context = self.get_serializer_context()
            context["request"] = request

            serializer = self.serializer_class(organization, context=context)
            data = serializer.data
            return Response(data, status=200)

    def _create_permissions(self, user, organization):
        content_type = ContentType.objects.get_for_model(Organization)
        org_permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=organization.id,
            organization=organization,
        )

        user_permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=organization.id,
            user=user,
        )
        return org_permission, user_permission

    def _create_image_file(self, data, organization, user):
        file_name = f"ORGANIZATION-IMAGE-{organization.id}--USER-{user.id}.txt"
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    def update(self, request, *args, **kwargs):
        user = request.user
        partial = kwargs.pop("partial", False)
        try:
            organization = self.get_object()
        except Http404:
            return Response({"data": "No permission to get organization"}, status=403)

        if not organization.org_has_admin_user(user):
            return Response({"data": "Invalid permissions"}, status=403)

        serializer = self.get_serializer(
            organization, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(organization, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            organization._prefetched_objects_cache = {}

        return Response(serializer.data)

    def destroy(self, request, pk=None):
        return Response(status=403)

    def _get_organization_users_context(self):
        context = {
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

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_organization_users(self, request, pk=None):
        organization = self.get_object()
        permissions = organization.permissions
        invited_users = (
            organization.invited_users.filter(accepted=False)
            .exclude(expiration_date__lt=datetime.now(pytz.utc))
            .distinct("recipient_email")
        )
        admin_user_ids = permissions.filter(
            access_type=ADMIN,
        ).values("user")
        member_user_ids = permissions.filter(
            access_type=MEMBER, organization__isnull=True
        ).values("user")
        admins = User.objects.filter(id__in=admin_user_ids)
        members = User.objects.filter(id__in=member_user_ids)
        all_users = admins.union(members)

        invited_users = invited_users.exclude(
            recipient__in=all_users.values("id"),
        ).filter(expiration_date__gt=datetime.now(pytz.utc))
        invitation_serializer = DynamicOrganizationInvitationSerializer(
            invited_users,
            _include_fields=[
                "accepted",
                "created_date",
                "expiration_date",
                "recipient_email",
            ],
            many=True,
        )
        user_count = all_users.count() + invited_users.count()
        note_count = organization.created_notes.count()

        context = self._get_organization_users_context()
        admin_serializer = DynamicUserSerializer(
            admins,
            many=True,
            context=context,
            _include_fields=["author_profile", "email", "id"],
        )
        member_serializer = DynamicUserSerializer(
            members,
            many=True,
            context=context,
            _include_fields=["author_profile", "email", "id"],
        )
        data = {
            "admins": admin_serializer.data,
            "members": member_serializer.data,
            "invited_users": invitation_serializer.data,
            "user_count": user_count,
            "note_count": note_count,
        }
        return Response(data, status=200)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def get_user_organizations(self, request, pk=None):
        if int(pk) == 0:
            user = request.user
        else:
            user = User.objects.get(id=pk)
        org_content_type = ContentType.objects.get_for_model(Organization)

        organization_ids = (
            user.permissions.annotate(
                org_id=Case(
                    When(content_type=org_content_type, then="object_id"),
                    When(
                        uni_doc_source__note__organization__isnull=False,
                        then="uni_doc_source__note__organization",
                    ),
                    output_field=models.PositiveIntegerField(),
                )
            )
            .filter(org_id__isnull=False)
            .values("org_id")
        )
        organizations = self.queryset.filter(id__in=organization_ids)

        serializer = DynamicOrganizationSerializer(
            organizations,
            context={
                "user": user,
                "usr_dos_get_user_permissions": {
                    "_include_fields": [
                        "access_type",
                    ]
                },
                "rag_dps_get_organization": {
                    "_include_fields": [
                        "id",
                        "slug",
                    ]
                },
            },
            _include_fields=[
                "created_date",
                "cover_image",
                "description",
                "member_count",
                "id",
                "name",
                "slug",
                "user_permission",
            ],
            many=True,
        )
        return Response(serializer.data, status=200)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_organization_by_key(self, request, pk=None):
        invite = OrganizationInvitation.objects.get(key=pk)
        organization = invite.organization
        serializer = self.serializer_class(organization)
        return Response(serializer.data, status=200)

    @action(
        detail=True,
        methods=["delete"],
        permission_classes=[IsAuthenticated, IsOrganizationAdmin],
    )
    def remove_user(self, request, pk=None):
        data = request.data
        user_id = data.get("user")
        organization = self.get_object()
        permissions = organization.permissions
        user_permission = permissions.get(user_id=user_id)

        if permissions.count() <= 1:
            return Response(
                {"data": "Organization needs at least one member"}, status=403
            )
        user_permission = permissions.remove(user_permission)
        return Response({"data": "User removed from Organization"}, status=200)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsOrganizationAdmin],
    )
    def invite_user(self, request, pk=None):
        inviter = request.user
        data = request.data
        try:
            organization = self.get_object()
        except Http404:
            return Response({"data": "No permission to get organization"}, status=403)

        access_type = data.get("access_type")
        recipient_email = data.get("email")
        time_to_expire = int(data.get("expire", 1440))

        if access_type not in (ADMIN, MEMBER):
            return Response({"data": "Invalid access type"}, status=400)

        recipient = User.objects.filter(email=recipient_email)
        if recipient.exists():
            recipient = recipient.first()
        else:
            recipient = None

        invite = OrganizationInvitation.create(
            inviter=inviter,
            recipient=recipient,
            recipient_email=recipient_email,
            organization=organization,
            invite_type=access_type,
            expiration_time=time_to_expire,
        )
        invite.send_invitation()
        return Response({"data": "Invite sent"}, status=200)

    @action(
        detail=True,
        methods=["patch"],
        permission_classes=[IsAuthenticated, IsOrganizationAdmin],
    )
    def remove_invited_user(self, request, pk=None):
        inviter = request.user
        data = request.data
        organization = self.get_object()
        recipient_email = data.get("email")

        invites = OrganizationInvitation.objects.filter(
            inviter=inviter,
            recipient_email=recipient_email,
            organization=organization,
        )
        invites.update(expiration_date=datetime.now(pytz.utc))
        return Response({"data": f"Invite removed for {recipient_email}"}, status=200)

    @action(
        detail=True,
        methods=["patch"],
        permission_classes=[IsAuthenticated, IsOrganizationAdmin],
    )
    def update_user_permission(self, request, pk=None):
        organization = self.get_object()
        data = request.data
        user_id = data.get("user")
        access_type = data.get("access_type")
        user_permission = organization.permissions.get(user=user_id)
        user_permission.access_type = access_type
        user_permission.save()
        return Response({"data": "User permission updated"}, status=200)

    @action(
        detail=True,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsOrganizationUser],
    )
    def get_organization_notes(self, request, pk=None):
        user = request.user
        if pk == "me":
            # No organization notes, retrieve user's notes
            # No permission necessary
            notes = Note.objects.filter(
                created_by=user, unified_document__is_removed=False
            )
        else:
            organization = self.get_object(slug=True)
            notes = organization.created_notes.filter(
                unified_document__is_removed=False
            )

        notes = notes.filter(
            (
                Q(unified_document__permissions__user=user)
                & ~Q(unified_document__permissions__access_type=NO_ACCESS)
            )
            | (
                ~Q(unified_document__permissions__access_type=NO_ACCESS)
                & Q(unified_document__permissions__organization__permissions__user=user)
            )
        ).distinct()

        notes = notes.prefetch_related(
            "unified_document__permissions",
        )
        context = self._get_org_notes_context()
        page = self.paginate_queryset(notes)
        serializer_data = DynamicNoteSerializer(
            page,
            _include_fields=[
                "access",
                "created_date",
                "id",
                "organization",
                "title",
                "updated_date",
            ],
            context=context,
            many=True,
        ).data
        return self.get_paginated_response(serializer_data)

    def _get_org_notes_context(self):
        context = {
            "nte_dns_get_organization": {
                "_include_fields": [
                    "cover_image",
                    "id",
                    "name",
                    "slug",
                ]
            }
        }
        return context

    @action(
        detail=True,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsOrganizationUser],
    )
    def get_organization_templates(self, request, pk=None):
        user = request.user

        if pk == "me":
            # No organization notes, retrieve user's templates
            # No permission necessary
            templates = NoteTemplate.objects.filter(
                Q(created_by=user) | Q(is_default=True)
            ).exclude(is_removed=True)
        else:
            organization = self.get_object(slug=True)
            templates = organization.created_templates.exclude(is_removed=True)
            templates = templates.union(
                NoteTemplate.objects.filter(is_default=True, is_removed=False)
            )

        serializer = NoteTemplateSerializer(templates, many=True)
        return Response(serializer.data, status=200)
