from rest_framework.test import APITestCase
from user.tests.helpers import (
    create_random_default_user,
    create_moderator,
)
from hub.tests.helpers import create_hub
from peer_review.tests.helpers import create_peer_review_request
from peer_review.models import PeerReviewRequest
from user.models import Organization, User
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)


class PeerReviewViewTests(APITestCase):
    def setUp(self):
      moderator = create_moderator(first_name='moderator', last_name='moderator')
      author = create_random_default_user('regular_user')
      peer_reviewer = create_random_default_user('peer_reviewer')

      # Create org
      self.client.force_authenticate(moderator)
      response = self.client.post('/api/organization/', {'name': 'test org'})
      self.org = response.data

      # Create review
      self.review_request_for_author = create_peer_review_request(
          requested_by_user=author,
          organization=Organization.objects.get(id=self.org['id']),
          title='Some random post title',
          body='some text',
      )

      # Invite user
      invite_response = self.client.post("/api/peer_review_invites/invite/",{
          'recipient': peer_reviewer.id,
          'peer_review_request': self.review_request_for_author.id,
      })

      # Retrieve request + details
      self.client.force_authenticate(peer_reviewer)
      response = self.client.post(f'/api/peer_review_invites/{invite_response.data["id"]}/accept/')

      self.peer_review = response.data['peer_review']

    def test_author_can_create_thread(self):
      unified_doc = ResearchhubUnifiedDocument.objects.get(
          id=self.peer_review['unified_document'],
      )
      author = self.review_request_for_author.requested_by_user

      print(author.id)
      print(self.peer_review['assigned_user'])

      invite_response = self.client.post(f'/api/peer_reviews/{self.peer_review["id"]}/discussion',{
          'plain_text': "some text",
          'peer_review_request': self.review_request_for_author.id,
      })

      # self.client.force_authenticate(author)
      # response = self.client.post(f'/api/peer_review_invites/{invite_response.data["id"]}/accept/')

