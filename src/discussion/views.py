from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import Thread
from .serializers import ThreadSerializer


class DiscussionViewSet(viewsets.ModelViewSet):
    serializer_class = ThreadSerializer

    # Optional attributes
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        paper_id = self.get_paper_id_from_path()
        threads = Thread.objects.filter(paper=paper_id)
        return threads

    def get_paper_id_from_path(self):
        SECOND = 1
        paper_id = None
        path_parts = self.request.path.split('/')
        if path_parts[SECOND] == 'paper':
            try:
                paper_id = int(path_parts[SECOND + 1])
            except ValueError:
                print('Failed to get paper id')
        return paper_id
