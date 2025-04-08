from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets

from discussion.reaction_serializers import VoteSerializer
from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_unified_document_views import get_user_votes


class BaseFeedView(viewsets.ModelViewSet):
    """
    Base class for feed-related viewsets.
    """

    _content_types = {}

    @property
    def _comment_content_type(self):
        return self._get_content_type(RhCommentModel)

    @property
    def _hub_content_type(self):
        return self._get_content_type(Hub)

    @property
    def _paper_content_type(self):
        return self._get_content_type(Paper)

    @property
    def _post_content_type(self):
        return self._get_content_type(ResearchhubPost)

    def _get_content_type(self, model_class):
        model_name = model_class.__name__.lower()
        if model_name not in self._content_types:
            self._content_types[model_name] = ContentType.objects.get_for_model(
                model_class
            )
        return self._content_types[model_name]

    def add_user_votes_to_response(self, user, response_data):
        """
        Add user votes to feed items in the response data.

        Args:
            user: The authenticated user
            response_data: The response data containing feed items
        """
        # Get uppercase model names from ContentType objects
        paper_type_str = self._paper_content_type.model.upper()
        post_type_str = self._post_content_type.model.upper()
        comment_type_str = self._comment_content_type.model.upper()

        paper_ids = []
        post_ids = []
        comment_ids = []

        # Collect IDs for each content type
        for item in response_data["results"]:
            content_type_str = item.get("content_type")
            if content_type_str == paper_type_str:
                paper_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == post_type_str:
                post_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == comment_type_str:
                comment_ids.append(int(item["content_object"]["id"]))

        # Process paper votes
        if paper_ids:
            paper_votes = get_user_votes(
                user,
                paper_ids,
                self._paper_content_type,
            )

            paper_votes_map = {}
            for vote in paper_votes:
                paper_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == paper_type_str:
                    paper_id = int(item["content_object"]["id"])
                    if paper_id in paper_votes_map:
                        item["user_vote"] = paper_votes_map[paper_id]

        # Process post votes
        if post_ids:
            post_votes = get_user_votes(
                user,
                post_ids,
                self._post_content_type,
            )

            post_votes_map = {}
            for vote in post_votes:
                post_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == post_type_str:
                    post_id = int(item["content_object"]["id"])
                    if post_id in post_votes_map:
                        item["user_vote"] = post_votes_map[post_id]

        # Process comment votes
        if comment_ids:
            comment_votes = get_user_votes(
                user,
                comment_ids,
                self._comment_content_type,
            )

            comment_votes_map = {}
            for vote in comment_votes:
                comment_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == comment_type_str:
                    comment_id = int(item["content_object"]["id"])
                    if comment_id in comment_votes_map:
                        item["user_vote"] = comment_votes_map[comment_id]
