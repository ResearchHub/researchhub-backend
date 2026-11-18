"""API for the artifacts the notebook and assistant chats' agents make.

``GET artifacts/<id>/`` returns an artifact with its latest version's content;
``?version=<n>`` picks an earlier one. A chat's activity feed names each
artifact version a turn wrote, so this is how a client loads one to show it.
Artifacts are private to the owner of the chat that made them: anyone else's
artifact id, or one from a removed chat, is a 404. Access is gated like the
chats themselves.
"""

from django.http import Http404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.services.artifact_service import ArtifactService


class ArtifactDetailView(APIView):
    permission_classes = [IsAuthenticated, ResearchAIBudgetPermission]

    def get(self, request, artifact_id):
        service = ArtifactService()
        artifact = service.get_for_user(request.user, artifact_id)
        if artifact is None:
            raise Http404
        number = request.query_params.get("version")
        if number is not None and not number.isdigit():
            raise Http404
        version = service.version(artifact, None if number is None else int(number))
        if version is None:
            raise Http404
        return Response(service.representation(artifact, version))
