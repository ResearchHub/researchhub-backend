from django.db.models import Q
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from citation.utils import get_paper_by_doi_url
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers.paper_serializers import PaperSubmissionSerializer
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

    def create(self, validated_data):
        request_data = self.context.get("request").data
        moderator_id = request_data.get("moderator")
        requestor_id = request_data.get("requestor")
        target_paper_id = request_data.get("target_paper_id")
        target_paper_doi = request_data.get("target_paper_doi")
        target_author_name = request_data.get("target_author_name")
        moderator = User.objects.filter(id=moderator_id).first()
        requestor = User.objects.filter(id=requestor_id).first()

        if target_paper_id:
            # An exception will be thrown if paper does not exist
            Paper.objects.get(id=target_paper_id)

        self.__check_uniqueness_on_create(
            requestor_id,
            target_paper_id,
            target_author_name,
            target_paper_doi,
        )

        # @kouts - Create PaperReward in an atomic manner
        # Then reference it in the AuthorClaimCase below

        case = AuthorClaimCase.objects.create(
            **validated_data,
            target_paper_id=target_paper_id,
            moderator=moderator,
            requestor=requestor,
            version=2,
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

    def get_requestor(self, case):
        serializer = UserSerializer(case.requestor)
        if serializer is not None:
            return serializer.data
        return None

    def __check_uniqueness_on_create(
        self, requestor_id, target_paper_id, target_author_name, target_paper_doi
    ):
        query = None
        if target_paper_id:
            query = Q(
                requestor__id=requestor_id,
                target_author_name=target_author_name,
                target_paper_id=target_paper_id,
                status__in=["OPEN", "INITIATED"],
            )
        if target_paper_doi:
            doi_query = Q(
                requestor__id=requestor_id,
                target_author_name=target_author_name,
                target_paper_doi=target_paper_doi,
                status__in=["OPEN", "INITIATED"],
            )
            if query:
                query = query | doi_query
            else:
                query = doi_query

        has_open_case = AuthorClaimCase.objects.filter(query).exists()

        if has_open_case:
            raise Exception(
                f"Attempting to open a duplicate case for author {target_author_name} in paper {target_paper_id}"
            )

        query = None
        if target_paper_id:
            query = Q(
                requestor__id=requestor_id,
                target_author_name=target_author_name,
                target_paper_id=target_paper_id,
                status__in=["APPROVED"],
            )
        if target_paper_doi:
            doi_query = Q(
                requestor__id=requestor_id,
                target_author_name=target_author_name,
                target_paper_doi=target_paper_doi,
                status__in=["APPROVED"],
            )
            if query:
                query = query | doi_query
            else:
                query = doi_query

        already_claimed = AuthorClaimCase.objects.filter(query).exists()

        if already_claimed:
            raise Exception(
                f"Author {target_author_name} already claimed for paper {target_paper_id}"
            )

    class Meta(object):
        model = AuthorClaimCase
        fields = [
            *EXPOSABLE_FIELDS,
            "provided_email",
            "status",
            "token_generated_time",
            "validation_attempt_count",
            "validation_token",
            "paper",
            "target_paper_doi",
            "target_paper_title",
            "target_author_name",
            "preregistration_url",
            "open_data_url",
        ]
        read_only_fields = [
            "status",
            "token_generated_time",
            "validation_attempt_count",
            "validation_token",
        ]
