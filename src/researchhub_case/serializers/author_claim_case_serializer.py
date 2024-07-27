from django.db import transaction
from django.db.models import Q
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from citation.utils import get_paper_by_doi_url
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers.paper_serializers import (
    AuthorshipSerializer,
    PaperSubmissionSerializer,
)
from reputation.related_models.paper_reward import PaperReward
from researchhub_case.models import AuthorClaimCase
from user.models import User
from user.related_models.user_verification_model import UserVerification
from user.serializers import UserSerializer
from utils.parsers import get_pure_doi

from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS


class AuthorClaimCaseSerializer(ModelSerializer):
    moderator = SerializerMethodField(method_name="get_moderator")
    requestor = SerializerMethodField()
    paper = SerializerMethodField(method_name="get_paper")
    authorship = SerializerMethodField()

    def create(self, validated_data):
        request_data = self.context.get("request").data
        moderator_id = request_data.get("moderator")
        requestor_id = request_data.get("requestor")
        target_paper_id = request_data.get("target_paper_id")
        authorship_id = request_data.get("authorship_id")
        open_data_url = request_data.get("open_data_url")
        preregistration_url = request_data.get("preregistration_url")
        moderator = User.objects.filter(id=moderator_id).first()
        requestor = User.objects.filter(id=requestor_id).first()

        # An exception will be thrown if paper does not exist
        paper = Paper.objects.get(id=target_paper_id)

        self.__check_uniqueness_on_create(
            requestor_id,
            target_paper_id,
            authorship_id,
        )

        with transaction.atomic():
            paper_reward = PaperReward.claim_paper_rewards(
                paper,
                requestor.author_profile,
                bool(open_data_url),
                bool(preregistration_url),
            )

            case = AuthorClaimCase.objects.create(
                **validated_data,
                authorship_id=authorship_id,
                target_paper_id=target_paper_id,
                moderator=moderator,
                requestor=requestor,
                version=2,
                paper_reward=paper_reward,
            )

        return case

    def get_paper(self, case):
        paper = case.target_paper
        if paper:
            obj = {
                "title": paper.title,
                "id": paper.id,
                "slug": paper.slug,
            }
            return obj
        else:
            return None

    def get_moderator(self, case):
        serializer = UserSerializer(case.moderator)
        if serializer is not None:
            return serializer.data
        return None

    def get_authorship(self, case):
        if case.authorship_id is None:
            return None

        serializer = AuthorshipSerializer(case.authorship)
        return serializer.data

    def get_requestor(self, case):
        serializer = UserSerializer(case.requestor)
        if serializer is not None:
            return serializer.data
        return None

    def __check_uniqueness_on_create(
        self, requestor_id, target_paper_id, authorship_id
    ):
        query_open_claim_already_exists_for_this_user = Q(
            requestor__id=requestor_id,
            target_paper_id=target_paper_id,
            status__in=["OPEN"],
        )

        has_open_case = AuthorClaimCase.objects.filter(
            query_open_claim_already_exists_for_this_user
        ).exists()

        query_approved_claim_already_exists_for_this_user = Q(
            requestor__id=requestor_id,
            target_paper_id=target_paper_id,
            status__in=["APPROVED"],
        )

        has_approved_case = AuthorClaimCase.objects.filter(
            query_approved_claim_already_exists_for_this_user
        ).exists()

        if has_open_case:
            raise Exception(
                f"User {requestor_id} already has an open claim for paper {target_paper_id}"
            )
        elif has_approved_case:
            raise Exception(
                f"User {requestor_id} already has an approved claim for paper {target_paper_id}"
            )

    class Meta(object):
        model = AuthorClaimCase
        fields = [
            *EXPOSABLE_FIELDS,
            "status",
            "token_generated_time",
            "validation_attempt_count",
            "validation_token",
            "paper",
            "preregistration_url",
            "open_data_url",
            "version",
            "authorship",
            "paper_reward",
        ]
        read_only_fields = [
            "status",
            "token_generated_time",
            "validation_attempt_count",
            "validation_token",
        ]
