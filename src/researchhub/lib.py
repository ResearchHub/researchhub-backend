from rest_framework.decorators import action
from utils.http import DELETE, GET, PATCH, POST, PUT

CREATED_LOCATIONS = {
    'FEED': 'FEED',
    'HUB': 'HUB',
    'PAPER': 'PAPER',
    'PROGRESS': 'PROGRESS',
}

CREATED_LOCATION_CHOICES = [
    (CREATED_LOCATIONS['FEED'], CREATED_LOCATIONS['FEED']),
    (CREATED_LOCATIONS['HUB'], CREATED_LOCATIONS['HUB']),
    (CREATED_LOCATIONS['PAPER'], CREATED_LOCATIONS['PAPER']),
    (CREATED_LOCATIONS['PROGRESS'], CREATED_LOCATIONS['PROGRESS']),
]


class ActionableViewSet:
    @action(detail=True, methods=[DELETE, PATCH, PUT])
    def censor(self, request, pk=None):
        raise NotImplementedError

    @action(detail=True, methods=[POST])
    def endorse(self, request, pk=None):
        raise NotImplementedError

    @endorse.mapping.delete
    def delete_endorse(self, request, pk=None):
        raise NotImplementedError

    @action(detail=True, methods=[POST])
    def flag(self, request, pk=None):
        raise NotImplementedError

    @flag.mapping.delete
    def delete_flag(self, request, pk=None):
        raise NotImplementedError

    @action(detail=True, methods=[PATCH, POST, PUT])
    def upvote(self, request, pk=None):
        raise NotImplementedError

    @action(detail=True, methods=[PATCH, POST, PUT])
    def downvote(self, request, pk=None):
        raise NotImplementedError

    @action(detail=True, methods=[GET])
    def user_vote(self, request, pk=None):
        raise NotImplementedError

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        raise NotImplementedError


def get_paper_id_from_path(request):
    PAPER_INDEX = 2
    paper_id = None
    path_parts = request.path.split('/')
    if path_parts[PAPER_INDEX] == 'paper':
        try:
            paper_id = int(path_parts[PAPER_INDEX + 1])
        except ValueError:
            print('Failed to get paper id')
    return paper_id
