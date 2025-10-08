from django.db.models import Prefetch
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from user_lists.models import List, ListItem
from user_lists.permissions import IsOwnerOrReadOnly
from user_lists.serializers import ListItemSerializer, ListSerializer


class _ListBaseViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ListItemViewSet(_ListBaseViewSet):
    serializer_class = ListItemSerializer

    def get_queryset(self):
        return ListItem.objects.select_related(
            "parent_list", "parent_list__created_by", "unified_document"
        ).filter(parent_list__created_by=self.request.user, is_removed=False)


class ListViewSet(_ListBaseViewSet):
    serializer_class = ListSerializer

    def get_queryset(self):
        return List.objects.for_user(self.request.user).prefetch_related(
            Prefetch(
                "items", queryset=ListItem.objects.select_related("unified_document")
            )
        )
