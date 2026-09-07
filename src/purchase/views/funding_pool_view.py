from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.models import FundingPool
from purchase.serializers.funding_pool_serializer import (
    DynamicFundingPoolSerializer,
    FundingPoolContributionSerializer,
)
from purchase.services.funding_pool_service import FundingPoolService
from user.related_models.follow_model import Follow


class FundingPoolViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FundingPool.objects.all()
    serializer_class = DynamicFundingPoolSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options", "post"]

    def dispatch(self, request, *args, **kwargs):
        self.funding_pool_service = kwargs.pop(
            "funding_pool_service", FundingPoolService()
        )
        return super().dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["pch_dfps_get_created_by"] = {
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

    @track_event
    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def create_contribution(self, request, *args, **kwargs):
        input_serializer = FundingPoolContributionSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        validated = input_serializer.validated_data

        try:
            pool = FundingPool.objects.get(id=kwargs.get("pk"))
        except FundingPool.DoesNotExist:
            return Response({"message": "Funding pool does not exist"}, status=400)

        _, error = self.funding_pool_service.create_contribution(
            user=request.user,
            pool=pool,
            amount=validated["amount"],
            currency=validated["amount_currency"],
            use_credits=validated["use_credits"],
        )

        if error:
            return Response({"message": error}, status=400)

        # Let the contributor follow the grant document when present
        grant = pool.grant
        document = grant.unified_document.get_document()
        if document is not None:
            Follow.objects.get_or_create(
                user=request.user,
                object_id=document.id,
                content_type=ContentType.objects.get_for_model(document),
            )

        pool.refresh_from_db()
        context = self.get_serializer_context()
        serializer = self.get_serializer(pool, context=context)
        return Response(serializer.data)
