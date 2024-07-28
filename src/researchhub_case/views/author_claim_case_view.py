from django.core.paginator import Paginator
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from hub.permissions import IsModerator
from researchhub.settings import TESTING
from researchhub_case.constants.case_constants import (
    ALLOWED_VALIDATION_ATTEMPT_COUNT,
    APPROVED,
    DENIED,
    INITIATED,
    INVALIDATED,
    NULLIFIED,
    OPEN,
)
from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from researchhub_case.tasks import after_approval_flow, after_rejection_flow
from user.related_models.user_verification_model import UserVerification
from utils.http import GET, POST
from utils.permissions import CreateOrReadOnly


class AuthorClaimCaseViewSet(ModelViewSet):
    ordering = ["-updated_date"]
    pagination_size = 10
    permission_classes = [IsAuthenticated, CreateOrReadOnly]
    queryset = AuthorClaimCase.objects.all()
    serializer_class = AuthorClaimCaseSerializer

    def get_queryset(self):
        return self.queryset.filter(requestor=self.request.user.id)

    def create(self, request, *args, **kwargs):
        if not self._can_claim_case(request):
            return Response("Author cannot claim case", status=403)

        try:
            return super().create(request, *args, **kwargs)
        except Exception as error:
            return Response(str(error.args), status=400)

    def retrieve(self, request, *args, **kwargs):
        return Response("Method not allowed to public", status=400)

    def _can_claim_case(self, request) -> bool:
        data = request.data
        user = request.user
        requestor_id = data.get("requestor")

        if user.moderator:
            return True

        user_verification = UserVerification.objects.filter(user_id=requestor_id)

        if not user_verification.exists():
            return False

        return user_verification.first().is_verified

    @action(detail=False, methods=[GET], permission_classes=[IsModerator])
    def count(self, request, pk=None):
        try:
            close_count = AuthorClaimCase.objects.filter(
                status__in=[APPROVED, DENIED, INVALIDATED, NULLIFIED]
            ).count()
            open_count = AuthorClaimCase.objects.filter(status__in=[OPEN]).count()
            return Response(
                data={"closed_count": close_count, "open_count": open_count}, status=200
            )
        except (KeyError, TypeError) as e:
            return Response(e, status=400)

    # Verify given requestor's email address
    @action(
        detail=False,
        methods=[POST],
        permission_classes=[IsAuthenticated],
    )
    def author_claim_token_validation(self, request, pk=None):
        try:
            validation_token = request.data.get("token")
            target_case = AuthorClaimCase.objects.get(
                status=INITIATED, validation_token=validation_token
            )
            invalidation_result = self._check_and_invalidate_case(
                target_case, request.user
            )
            if invalidation_result is not None:
                return invalidation_result

            target_case.status = OPEN
            target_case.save()
            return Response("SUCCESS", status=200)

        except (KeyError, TypeError) as e:
            return Response(e, status=400)

    # Get / post author claim cases for Moderators
    @action(
        detail=False,
        methods=[GET, POST],
        permission_classes=[IsModerator],
    )
    def moderator(self, request, pk=None):
        if request.method == GET:
            return self._get_author_claim_cases_for_mods(request)
        else:
            return self._post_author_claim_cases_for_mods(request)

    def _check_and_invalidate_case(self, target_case, current_user):
        attempt_count = target_case.validation_attempt_count
        if ALLOWED_VALIDATION_ATTEMPT_COUNT < attempt_count:
            target_case.status = INVALIDATED
            target_case.save()
            return Response("DENIED_TOO_MANY_ATTEMPS", status=400)

        if target_case.requestor.id != current_user.id:
            target_case.validation_attempt_count += 1
            target_case.save()
            return Response("DENIED_WRONG_USER", status=400)

    def _get_author_claim_cases_for_mods(self, request):
        try:
            case_status = request.query_params.get("case_status")
            if case_status == "CLOSED":
                case_query_status = [APPROVED, DENIED, INVALIDATED, NULLIFIED]
            elif case_status == "OPEN":
                case_query_status = [OPEN]
            else:
                return Response("Bad case status", status=400)

            target_case_set = AuthorClaimCase.objects.filter(
                status__in=case_query_status,
                version=2,
            ).order_by("-updated_date")
            page = self.paginate_queryset(target_case_set)
            serializer = self.serializer_class(page, many=True)
            serializer_data = serializer.data
            return self.get_paginated_response(serializer_data)

        except (KeyError, TypeError) as e:
            return Response(e, status=400)

    def _post_author_claim_cases_for_mods(self, request):
        try:
            request_data = request.data
            update_status = request_data["update_status"]
            case_id = request_data["case_id"]
            case = AuthorClaimCase.objects.get(id=case_id, status=OPEN)

            if update_status == APPROVED:
                if case.target_paper is None and case.target_paper_doi is None:
                    return Response(
                        "Cannot approve. No paper id or DOI found.", status=400
                    )

                case.status = update_status
                case.save()

                if TESTING:
                    after_approval_flow(case_id)
                else:
                    after_approval_flow.apply((case_id,), priority=2, countdown=5)

                serializer = self.serializer_class(case)
                return Response(serializer.data, status=200)
            elif update_status == DENIED:
                notify_user = request_data["notify_user"]
                after_rejection_flow.apply_async(
                    (case_id, notify_user), priority=2, countdown=5
                )
                case.status = update_status
                case.save()
                return Response("Success", status=200)
            else:
                return Response("Unrecognized status", status=400)
        except (KeyError, TypeError) as e:
            return Response(e, status=400)
