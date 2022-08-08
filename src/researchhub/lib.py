from rest_framework.decorators import action

from utils.http import DELETE, GET, PATCH, POST, PUT

CREATED_LOCATIONS = {
    "FEED": "FEED",
    "HUB": "HUB",
    "PAPER": "PAPER",
    "PROGRESS": "PROGRESS",
}

CREATED_LOCATION_CHOICES = [
    (CREATED_LOCATIONS["FEED"], CREATED_LOCATIONS["FEED"]),
    (CREATED_LOCATIONS["HUB"], CREATED_LOCATIONS["HUB"]),
    (CREATED_LOCATIONS["PAPER"], CREATED_LOCATIONS["PAPER"]),
    (CREATED_LOCATIONS["PROGRESS"], CREATED_LOCATIONS["PROGRESS"]),
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


def get_document_id_from_path(request):
    DOCUMENT_INDEX = 2
    document_id = None
    path_parts = request.path.split("/")

    if path_parts[DOCUMENT_INDEX] in (
        "paper",
        "post",
        "hypothesis",
        "citation",
        "peer_review",
        "researchhub_post",
    ):
        try:
            document_id = int(path_parts[DOCUMENT_INDEX + 1])
        except ValueError:
            print("Failed to get document id")
    return document_id
