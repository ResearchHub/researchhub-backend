from allauth.socialaccount.models import SocialAccount
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import JSONField, Sum
from django.db.models.deletion import SET_NULL

from paper.utils import PAPER_SCORE_Q_ANNOTATION
from researchhub_case.constants.case_constants import APPROVED
from user.related_models.profile_image_storage import ProfileImageStorage
from user.related_models.school_model import University
from user.related_models.user_model import User

fs = ProfileImageStorage()


class Author(models.Model):
    user = models.OneToOneField(
        User,
        related_name="author_profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    first_name = models.CharField(max_length=30)  # Same max_length as User
    last_name = models.CharField(max_length=150)  # Same max_length as User
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    description = models.TextField(null=True, blank=True)
    h_index = models.IntegerField(default=0)
    profile_image = models.FileField(
        upload_to="uploads/author_profile_images/%Y/%m/%d",
        max_length=1024,
        default=None,
        null=True,
        blank=True,
        storage=fs,
    )
    author_score = models.IntegerField(default=0)
    university = models.ForeignKey(
        University, on_delete=models.SET_NULL, null=True, blank=True
    )
    orcid_id = models.CharField(
        max_length=1024, default=None, null=True, blank=True, unique=True
    )
    orcid_account = models.ForeignKey(
        SocialAccount, on_delete=models.SET_NULL, null=True, blank=True
    )
    openalex_ids = ArrayField(
        models.CharField(
            max_length=64, default=None, null=True, blank=True, unique=True
        ),
        null=False,
        default=list,
    )
    education = ArrayField(
        JSONField(blank=True, null=True), default=list, blank=True, null=True
    )
    headline = JSONField(blank=True, null=True)
    facebook = models.URLField(max_length=255, default=None, null=True, blank=True)
    twitter = models.URLField(max_length=255, default=None, null=True, blank=True)
    linkedin = models.URLField(max_length=255, default=None, null=True, blank=True)
    google_scholar = models.URLField(
        max_length=255, default=None, null=True, blank=True
    )
    linkedin_data = models.JSONField(null=True, blank=True)
    academic_verification = models.BooleanField(default=None, null=True, blank=True)
    claimed = models.BooleanField(default=True, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    merged_with = models.ForeignKey("self", on_delete=SET_NULL, null=True, blank=True)

    def __str__(self):
        university = self.university
        if university is None:
            university_name = ""
            university_city = ""
        else:
            university_name = university.name
            university_city = university.city
        return (
            f"{self.first_name}_{self.last_name}_{university_name}_"
            f"{university_city}"
        )

    @property
    def full_name(self):
        return self.first_name + " " + self.last_name

    @property
    def profile_image_indexing(self):
        if self.profile_image is not None:
            try:
                return self.profile_image.url
            except ValueError:
                return str(self.profile_image)
        return None

    @property
    def person_types_indexing(self):
        person_types = ["author"]
        if self.user is not None:
            person_types.append("user")

        return person_types

    @property
    def university_indexing(self):
        if self.university is not None:
            return self.university
        return None

    @property
    def user_reputation_indexing(self):
        if self.user is not None:
            return self.user.reputation
        return 0

    @property
    def is_claimed(self):
        return (
            self.user is not None
            or self.user is None
            and self.related_claim_cases.filter(status=APPROVED).exists()
        )

    @property
    def claimed_by_user_author_id(self):
        approved_claim_case = self.related_claim_cases.filter(status=APPROVED).first()
        if self.user is not None:
            return self.id
        elif approved_claim_case is not None:
            return approved_claim_case.requestor.author_profile.id
        else:
            return None

    def get_expertise_hubs(self):
        pass

    def get_top_hubs(self, max_results=10):
        from researchhub_comment.related_models.rh_comment_model import RhCommentModel
        from researchhub_document.related_models.researchhub_unified_document_model import (
            UnifiedDocumentConcepts,
        )

        # Contains all hubs associated with user's authored papers ordered by relevance
        expertise_hubs = []

        # All Unified Documents associated with records (peer review, authored paper, etc.)
        # which will be used to get relevant concepts and related hubs
        related_unified_documents = []

        # Get unified documents associated with authored papers
        authored_papers = self.authored_papers.all()
        for authored_paper in authored_papers:
            related_unified_documents.append(authored_paper.unified_document)

        # Get unified documents associated with peer reviews
        peer_reviews = RhCommentModel.objects.filter(
            comment_type__in=["REVIEW"], created_by_id=self.user.id
        )
        for review in peer_reviews:
            related_unified_documents.append(review.unified_document)

        # Get relevant concepts associated with unified documents
        concepts = UnifiedDocumentConcepts.objects.filter(
            unified_document__in=related_unified_documents
        ).order_by("-relevancy_score")

        expertise_hubs = [hub for hub in concepts]

        return expertise_hubs[:max_results]

    def calculate_score(self):
        aggregated_score = self.authored_papers.annotate(
            paper_score=PAPER_SCORE_Q_ANNOTATION
        ).aggregate(total_score=Sum("paper_score"))
        aggregated_discussion_count = self.authored_papers.aggregate(
            total_score=Sum("discussion_count")
        )
        paper_count = self.authored_papers.count()
        paper_scores = 0
        if aggregated_score["total_score"]:
            paper_scores = aggregated_score["total_score"]

        if aggregated_discussion_count["total_score"]:
            paper_scores += 2 * aggregated_discussion_count["total_score"]

        return paper_scores + paper_count
