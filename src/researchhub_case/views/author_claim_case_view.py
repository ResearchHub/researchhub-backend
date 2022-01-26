from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated

from hub.permissions import IsModerator
from researchhub_case.constants.case_constants import (
    ALLOWED_VALIDATION_ATTEMPT_COUNT, 
    APPROVED, DENIED, INITIATED, INVALIDATED, NULLIFIED, OPEN
)
from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from utils.http import GET, POST


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = AuthorClaimCase.objects.all().order_by("-created_date")
    serializer_class = AuthorClaimCaseSerializer

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except Exception as error:
            return Response(str(error.args), status=400)

    def retrieve(self, request, *args, **kwargs):
        return Response('Method not allowed to public', status=400)

    @action(
        detail=False,
        methods=[GET],
        permission_classes=[IsModerator]
    )
    def count(self, request, pk=None):
        try:
            close_count = AuthorClaimCase.objects.filter(
                status__in=[APPROVED, DENIED, INVALIDATED, NULLIFIED]
            ).count()
            open_count = AuthorClaimCase.objects.filter(
                status__in=[OPEN]
            ).count()
            return Response(
                data={
                    'closed_count': close_count,
                    'open_count': open_count
                },
                status=200
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
            validation_token = request.data.get('token')
            target_case = AuthorClaimCase.objects.get(
                status=INITIATED,
                validation_token=validation_token
            )
            invalidation_result = self._check_and_invalidate_case(
                target_case,
                request.user
            )
            if (invalidation_result is not None):
                return invalidation_result
            
            target_case.status = OPEN
            target_case.save()
            return Response('SUCCESS',  status=200)

        except (KeyError, TypeError) as e:
            return Response(e, status=400)

    # Get / post author claim cases for Moderators
    @action(
        detail=False,
        methods=[GET, POST],
        permission_classes=[IsModerator],
    )
    def moderator(self, request, pk=None):
        if (request.method == GET):
            return self._get_author_claim_cases_for_mods(request)
        else:
            return self._post_author_claim_cases_for_mods(request)

    def _check_and_invalidate_case(self, target_case, current_user):
        attempt_count = target_case.validation_attempt_count
        if (ALLOWED_VALIDATION_ATTEMPT_COUNT < attempt_count):
            target_case.status = INVALIDATED
            target_case.save()
            return Response('DENIED_TOO_MANY_ATTEMPS', status=400)
            
        if (target_case.requestor.id != current_user.id):
            target_case.validation_attempt_count += 1
            target_case.save()
            return Response('DENIED_WRONG_USER', status=400)

    def _get_author_claim_cases_for_mods(self, request):
        # TODO: calvinhlee - paginate this
        try:
            case_status = request.query_params.get('case_status')
            if (case_status == 'CLOSED'):
                case_query_status = [APPROVED, DENIED, INVALIDATED, NULLIFIED]
            elif (case_status == 'OPEN'):
                case_query_status = [OPEN]
            else:
                return Response('Bad case status', status=400)

            target_case_set = AuthorClaimCase.objects.filter(
                status__in=case_query_status
            )
            serialized_result = AuthorClaimCaseSerializer(
                target_case_set,
                many=True
            )
            return Response(data=serialized_result.data, status=200)
        except (KeyError, TypeError) as e:
            return Response(e, status=400)

    def _post_author_claim_cases_for_mods(self, request):
        try:
            request_data = request.data
            update_status = request_data['update_status']
            if (update_status not in ['APPROVED', 'DENIED']):
                return Response('Base update status', status=400)

            case_id = request_data['case_id']
            case = AuthorClaimCase.objects.get(id=case_id, status=OPEN)
            case.status = APPROVED if update_status == "APPROVED" else DENIED
            case.save()
            return Response('Success', status=200)
        except (KeyError, TypeError) as e:
            return Response(e, status=400)
