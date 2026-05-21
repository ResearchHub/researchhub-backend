from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import NewFeatureClick
from .serializers import NewFeatureClickSerializer


class NewFeatureViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "head", "options", "post"]
    permission_classes = [IsAuthenticated]
    queryset = NewFeatureClick.objects.all()
    serializer_class = NewFeatureClickSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(user=self.request.user).order_by("id")

    @action(
        detail=False,
        methods=["GET"],
    )
    def clicked(self, request):
        feature = request.GET.get("feature")
        user_clicked = self.get_queryset().filter(feature=feature).exists()

        return Response({"clicked": user_clicked}, status=200)
