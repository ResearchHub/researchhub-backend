from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import JSONField, Sum
from django.db.models.deletion import SET_NULL

from discussion.reaction_models import Vote
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from paper.utils import PAPER_SCORE_Q_ANNOTATION
from purchase.related_models.purchase_model import Purchase
from reputation.models import (
    Bounty,
    Contribution,
    Distribution,
    Score,
    ScoreChange,
    Withdrawal,
)
from researchhub_case.constants.case_constants import APPROVED
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from user.related_models.profile_image_storage import ProfileImageStorage
from user.related_models.school_model import University
from user.related_models.user_model import User

fs = ProfileImageStorage()


class Author(models.Model):
    SOURCE_OPENALEX = "OPENALEX"
    SOURCE_RESEARCHHUB = "RESEARCHHUB"
    SOURCE_CHOICES = [
        (SOURCE_OPENALEX, "OpenAlex"),
        (SOURCE_RESEARCHHUB, "ResearchHub"),
    ]
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
    i10_index = models.IntegerField(default=0)
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
        max_length=1024, default=None, null=True, blank=True, unique=False
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
    claimed = models.BooleanField(default=True, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    country_code = models.CharField(
        blank=True,
        null=True,
        max_length=20,
    )

    # Indicates whether the user was created through the RH platform or through another source such as OpenAlex
    created_source = models.CharField(
        max_length=20,
        null=False,
        blank=False,
        choices=SOURCE_CHOICES,
        default=SOURCE_RESEARCHHUB,
    )

    # Indicates the last time we did a full fetch from OpenAlex which includes all the works
    last_full_fetch_from_openalex = models.DateTimeField(null=True, blank=True)

    # AKA Impact Factor. Derived from OpenAlex:  https://en.wikipedia.org/wiki/Impact_factor
    two_year_mean_citedness = models.FloatField(default=0)

    # An author's profile can be merged with another author's
    merged_with_author = models.ForeignKey(
        "self",
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="merged_authors",
    )

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
    def open_access_pct(self):
        authorships = Authorship.objects.filter(author=self)
        authored_papers = Paper.objects.filter(
            id__in=authorships.values_list("paper_id", flat=True),
        )

        total_paper_count = authored_papers.count()

        if total_paper_count == 0:
            return 0
        else:
            return (
                authored_papers.filter(is_open_access=True).count() / total_paper_count
            )

    @property
    def citation_count(self):
        from django.db.models import Sum

        paper_citations_res = (
            Authorship.objects.filter(author=self)
            .select_related("paper")
            .aggregate(
                citation_count=Sum("paper__citations"),
            )
        )

        return paper_citations_res.get("citation_count") or 0

    @property
    def paper_count(self):
        from django.db.models import Count

        paper_count_res = (
            Authorship.objects.filter(author=self)
            .select_related("paper")
            .aggregate(
                paper_count=Count("paper"),
            )
        )

        return paper_count_res.get("paper_count") or 0

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
    def achievements(self):
        upvote_count = getattr(self.user, "upvote_count", 0)
        peer_review_count = getattr(self.user, "peer_review_count", 0)
        amount_funded = getattr(self.user, "amount_funded", 0)

        achievements = []
        if self.citation_count >= 1:
            achievements.append("CITED_AUTHOR")
        if self.open_access_pct >= 0.5:
            achievements.append("OPEN_ACCESS")
        if amount_funded > 1:
            achievements.append("OPEN_SCIENCE_SUPPORTER")

        if upvote_count >= 1000:
            achievements.append("HIGHLY_UPVOTED_5")
        elif upvote_count >= 500:
            achievements.append("HIGHLY_UPVOTED_4")
        elif upvote_count >= 100:
            achievements.append("HIGHLY_UPVOTED_3")
        elif upvote_count >= 25:
            achievements.append("HIGHLY_UPVOTED_2")
        elif upvote_count >= 10:
            achievements.append("HIGHLY_UPVOTED_1")

        if peer_review_count >= 250:
            achievements.append("EXPERT_PEER_REVIEWER_5")
        elif peer_review_count >= 100:
            achievements.append("EXPERT_PEER_REVIEWER_4")
        elif peer_review_count >= 25:
            achievements.append("EXPERT_PEER_REVIEWER_3")
        elif peer_review_count >= 5:
            achievements.append("EXPERT_PEER_REVIEWER_2")
        elif peer_review_count >= 1:
            achievements.append("EXPERT_PEER_REVIEWER_1")

        return achievements

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

    # Gets ranked list of hubs associated with user's interests.
    # We use comments and votes to determine what is the user interested in
    def get_interest_hubs(self, max_results=100, min_relevancy_score=0.2):
        from researchhub_comment.related_models.rh_comment_model import RhCommentModel
        from researchhub_document.related_models.researchhub_unified_document_model import (
            UnifiedDocumentConcepts,
        )

        # Contains all hubs associated with user's interests ordered by relevance
        # Comments, votes
        interest_hubs = []

        # All Unified Documents associated with records
        # which will be used to get related hubs
        related_unified_documents = []

        # Get unified documents associated with comments
        comments = RhCommentModel.objects.filter(created_by_id=self.user.id)

        for comment in comments:
            related_unified_documents.append(comment.unified_document)

        # Get all unified docs associated with user votes
        user_votes = Vote.objects.filter(created_by_id=self.user.id)

        for vote in user_votes:
            try:
                related_unified_documents.append(vote.item.unified_document)
            except Exception as e:
                pass

        # Get all items the user spend RSC on
        purchases = Purchase.objects.filter(user_id=self.user.id)

        for purchase in purchases:
            try:
                related_unified_documents.append(purchase.item.unified_document)
            except Exception as e:
                pass

        # Get relevant concepts associated with unified documents
        ranked_concepts = UnifiedDocumentConcepts.objects.filter(
            unified_document__in=related_unified_documents
        ).order_by("-relevancy_score")

        # Get hubs associated with concepts
        interest_hubs = [
            ranked.concept.hub
            for ranked in ranked_concepts
            if ranked.relevancy_score >= min_relevancy_score
            and hasattr(ranked.concept, "hub")
        ]

        # It is quite possible that hubs returned through ranked concepts is less than max_results
        # As a result, we want to pad the list with the rest of the hubs
        for doc in related_unified_documents:
            if hasattr(doc, "hubs"):
                interest_hubs = interest_hubs + list(doc.hubs.all())

        # Remove duplicates while preserving order
        seen = set()
        interest_hubs = [x for x in interest_hubs if not (x in seen or seen.add(x))]

        return interest_hubs[:max_results]

    # Gets ranked list of hubs associated with user's likely expertise.
    # We use content peer reviewed and published papers to determine expertise
    def get_expertise_hubs(self, max_results=100, min_relevancy_score=0.2):
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
        ranked_concepts = UnifiedDocumentConcepts.objects.filter(
            unified_document__in=related_unified_documents
        ).order_by("-relevancy_score")

        # Omit concepts with relevancy score below threshold
        expertise_hubs = [
            ranked.concept.hub
            for ranked in ranked_concepts
            if ranked.relevancy_score >= min_relevancy_score
            and hasattr(ranked.concept, "hub")
        ]

        # It is quite possible that hubs returned through ranked concepts is less than max_results
        # As a result, we want to pad the list with the rest of the hubs
        for doc in related_unified_documents:
            if hasattr(doc, "hubs"):
                expertise_hubs = expertise_hubs + list(doc.hubs.all())

        # Remove duplicates while preserving order
        seen = set()
        expertise_hubs = [x for x in expertise_hubs if not (x in seen or seen.add(x))]

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

    def calculate_hub_scores(self, recalculate=False):
        if recalculate:
            Score.incrememnt_version(self)

        with transaction.atomic():
            self._calculate_score_hub_citations()
            self._calculate_score_hub_paper_votes()
            self._calculate_score_hub_comments()

    def _calculate_score_hub_paper_votes(self):
        authorships = Authorship.objects.filter(author=self)
        authored_papers = Paper.objects.filter(
            id__in=authorships.values_list("paper_id", flat=True),
            work_type__in=["preprint", "article"],
        )

        for paper in authored_papers:
            votes = paper.votes.filter(vote_type__in=[1, 2])
            if votes.count() == 0:
                continue

            hub = paper.unified_document.get_primary_hub()
            if hub is None:
                print(f"Paper {paper.id} has no primary hub")
                continue

            for vote in votes:
                self.update_scores_vote(vote, hub)

    def _calculate_score_hub_comments(self):
        threads = RhCommentThreadModel.objects.filter(
            content_type=ContentType.objects.get(model="paper"),
            created_by=self.user,
        )

        for thread in threads:
            comments = thread.rh_comments.all()
            for comment in comments:
                paper = Paper.objects.get(id=comment.thread.object_id)
                votes = comment.votes.filter(vote_type__in=[1, 2])
                if votes.count() == 0:
                    continue

                hub = paper.unified_document.get_primary_hub()
                if hub is None:
                    print(f"Paper {paper.id} has no primary hub")
                    continue

                for vote in votes:
                    self.update_scores_vote(vote, hub)

    def _calculate_score_hub_citations(self):
        authorships = Authorship.objects.filter(author=self)
        authored_papers = Paper.objects.filter(
            id__in=authorships.values_list("paper_id", flat=True),
            work_type__in=["preprint", "article"],
        )

        for paper in authored_papers:
            historical_papers = paper.history.all().order_by("history_date")
            if len(historical_papers) == 0:
                historical_papers = [paper]

            hub = paper.unified_document.get_primary_hub()
            if hub is None:
                print(f"Paper {paper.id} has no primary hub")
                continue

            for i, historical_paper in enumerate(historical_papers):
                previous_historical_paper = None
                if i != 0:
                    previous_historical_paper = historical_papers[i - 1]

                self.update_scores_citation(
                    historical_paper,
                    previous_historical_paper,
                    hub,
                )

    def update_scores_citation(self, historical_paper, previous_historical_paper, hub):
        citation_change = historical_paper.citation_change(previous_historical_paper)
        if citation_change == 0:
            return

        paper_id = historical_paper.id
        content_type = ContentType.objects.get_for_model(Paper)
        if isinstance(historical_paper, Paper.history.model):
            paper_id = historical_paper.history_id
            content_type = ContentType.objects.get_for_model(Paper.history.model)

        try:
            score = Score.objects.select_for_update().get(
                hub=hub,
                author=self,
            )
            previous_score_change = ScoreChange.objects.get(
                score=score,
                changed_object_id=paper_id,
                changed_content_type=content_type,
                score_version=score.version,
            )
        except (Score.DoesNotExist, ScoreChange.DoesNotExist):
            previous_score_change = None

        if previous_score_change:
            return

        Score.update_score(
            self,
            hub,
            citation_change,
            "citations",
            content_type,
            paper_id,
        )

    def update_scores_vote(self, vote, hub):
        content_type = ContentType.objects.get_for_model(Vote)

        score = Score.get_or_create_score(self, hub)
        previous_score_change = (
            ScoreChange.objects.filter(
                score=score,
                changed_object_id=vote.id,
                changed_content_type=content_type,
                score_version=score.version,
            )
            .order_by("created_date")
            .last()
        )
        vote_value = ScoreChange.vote_change(vote, previous_score_change)
        if vote_value == 0:
            return

        Score.update_score(
            self,
            hub,
            vote_value,
            "votes",
            content_type,
            vote.id,
        )

    def get_rep_score(self):
        score = Score.get_max_score(self)
        if score is None:
            return 0

        return score.score
