"""API for the user-selectable model catalog.

One listing serves every agent workflow that takes a model selection (the
notebook assistant and proposal drafting): the pickers render the same
catalog, and a submitted ``model`` must name one of these refs. Gated like
those workflows so the roster is not readable outside the rollout group.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.services.agent import available_models, default_model_ref
from research_ai.services.agent.model_capabilities import EFFORT_LEVELS
from research_ai.services.agent.model_pricing import cost_multiplier, model_pricing
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.usage_budget import budget_status, resolve_ai_tier


class AvailableModelsView(APIView):
    """List the models a user may select, and which ref runs by default."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIBudgetPermission,
    ]

    def get(self, request):
        policy = resolve_ai_tier(request.user)
        tier_default = policy.default_model_ref or default_model_ref()

        def capabilities(option):
            payload = option.capabilities.as_dict()
            if policy.max_effort is not None:
                maximum = EFFORT_LEVELS.index(policy.max_effort)
                payload["effort"] = [
                    value
                    for value in payload["effort"]
                    if EFFORT_LEVELS.index(value) <= maximum
                ]
            if policy.allowed_thinking_modes is not None:
                payload["thinking"] = [
                    value
                    for value in payload["thinking"]
                    if value in policy.allowed_thinking_modes
                ]
            return payload

        def allowed(option):
            entitled = (
                policy.allowed_model_refs is None
                or option.ref in policy.allowed_model_refs
            )
            provider, model_id = split_model_ref(option.ref)
            priced = model_pricing(provider, model_id or "") is not None
            return entitled and (not policy.is_budgeted or priced)

        return Response(
            {
                "default": tier_default,
                "models": [
                    {
                        "ref": option.ref,
                        "label": option.label,
                        "description": option.description,
                        "provider": option.provider,
                        "capabilities": capabilities(option),
                        "allowed": allowed(option),
                        "multiplier": (
                            str(multiplier)
                            if (multiplier := cost_multiplier(option.ref)) is not None
                            else None
                        ),
                    }
                    for option in available_models()
                ],
            }
        )


class UsageBudgetStatusView(APIView):
    """Return today's UTC budget meter for the authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(budget_status(request.user).as_dict())
