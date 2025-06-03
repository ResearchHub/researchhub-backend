from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.models import Grant, GrantApplication
from purchase.serializers.grant_create_serializer import GrantCreateSerializer
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.permissions import IsModerator


class GrantViewSet(viewsets.ModelViewSet):
    queryset = Grant.objects.all()
    serializer_class = DynamicGrantSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        """
        Only moderators can create, update, or delete grants.
        Anyone authenticated can view grants.
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsModerator()]
        return super().get_permissions()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["pch_dgs_get_created_by"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["usr_dus_get_author_profile"] = {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            )
        }
        return context

    def create(self, request, *args, **kwargs):
        """
        Create a new grant. Only moderators can create grants.
        """
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        with transaction.atomic():
            grant = Grant.objects.create(
                created_by=request.user,
                unified_document=validated_data["unified_document"],
                amount=validated_data["amount"],
                currency=validated_data["currency"],
                organization=validated_data["organization"],
                description=validated_data["description"],
                end_date=validated_data.get("end_date"),
            )

        context = self.get_serializer_context()
        response_serializer = self.get_serializer(grant, context=context)
        return Response(response_serializer.data, status=201)

    def update(self, request, *args, **kwargs):
        """
        Update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.is_moderator():
            return Response({"message": "Permission denied"}, status=403)

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.is_moderator():
            return Response({"message": "Permission denied"}, status=403)

        return super().partial_update(request, *args, **kwargs)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def close(self, request, *args, **kwargs):
        """
        Close a grant (set status to CLOSED). Only moderators can close grants.
        """
        grant = self.get_object()

        if grant.status == Grant.CLOSED:
            return Response({"message": "Grant is already closed"}, status=400)

        grant.status = Grant.CLOSED
        grant.save()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def complete(self, request, *args, **kwargs):
        """
        Mark a grant as completed (set status to COMPLETED). Only moderators can complete grants.
        """
        grant = self.get_object()

        if grant.status == Grant.COMPLETED:
            return Response({"message": "Grant is already completed"}, status=400)

        grant.status = Grant.COMPLETED
        grant.save()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def reopen(self, request, *args, **kwargs):
        """
        Reopen a grant (set status to OPEN). Only moderators can reopen grants.
        """
        grant = self.get_object()

        if grant.status == Grant.OPEN:
            return Response({"message": "Grant is already open"}, status=400)

        grant.status = Grant.OPEN
        grant.save()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def application(self, request, pk=None):
        """Apply to a grant with a preregistration post."""
        grant = self.get_object()
        preregistration_post_id = request.data.get("preregistration_post_id")

        # Validation
        try:
            post = ResearchhubPost.objects.get(
                id=preregistration_post_id,
                created_by=request.user,
                document_type=PREREGISTRATION,
            )
        except ResearchhubPost.DoesNotExist:
            return Response({"error": "Invalid preregistration post"}, status=400)

        # Check if grant is still active
        if not grant.is_active():
            return Response(
                {"error": "Grant is no longer accepting applications"}, status=400
            )

        # Create application
        application, created = GrantApplication.objects.get_or_create(
            grant=grant, preregistration_post=post, applicant=request.user
        )

        if created:
            return Response({"message": "Application submitted"}, status=201)
        else:
            return Response({"message": "Already applied"}, status=200)
