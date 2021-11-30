from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import NewFeatureClick
from .serializers import NewFeatureClickSerializer

class NewFeatureViewSet(viewsets.ModelViewSet):
    queryset = NewFeatureClick.objects.all()
    serializer_class = NewFeatureClickSerializer


    @action(
        detail=False,
        methods=['GET'],
    )
    def clicked(self, request):
        user = request.user
        feature = request.GET.get('feature')
        user_clicked = self.queryset.filter(user=user, feature=feature).exists()

        return Response(
            {'clicked': user_clicked},
            status=200
        )