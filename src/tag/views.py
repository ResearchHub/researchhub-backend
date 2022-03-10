from rest_framework import viewsets
from django.http import JsonResponse
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)

from .models import Tag


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    permission_classes = [
        IsAuthenticatedOrReadOnly
    ]

    def list(self, request):
        search = request.query_params.get("search")
        limit = int(request.query_params.get("limit", 1000))

        if search:
            self.queryset = self.queryset.filter(key__contains=search.lower())[:limit]
        else:
            self.queryset = self.queryset[:limit]

        return JsonResponse({"tags": [{"id": k.id, "key": k.key} for k in self.queryset]})
