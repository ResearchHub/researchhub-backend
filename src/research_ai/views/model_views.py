"""API for the user-selectable model catalog.

One listing serves every agent workflow that takes a model selection (the
notebook assistant and proposal drafting): the pickers render the same
catalog, and a submitted ``model`` must name one of these refs. Gated like
those workflows so the roster is not readable outside the rollout group.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIPermission
from research_ai.services.agent import available_models, default_model_ref
from user.permissions import IsModerator, UserIsEditor


class AvailableModelsView(APIView):
    """List the models a user may select, and which ref runs by default."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request):
        return Response(
            {
                "default": default_model_ref(),
                "models": [
                    {
                        "ref": option.ref,
                        "label": option.label,
                        "description": option.description,
                        "provider": option.provider,
                        "capabilities": option.capabilities.as_dict(),
                    }
                    for option in available_models()
                ],
            }
        )
