# from rest_framework.test import APITestCase
# from user.tests.helpers import (
#     create_random_default_user,
#     create_moderator,
# )
# from hub.tests.helpers import create_hub
# from peer_review.tests.helpers import create_peer_review_request
# from peer_review.models import (
#     PeerReviewRequest,
#     PeerReview
# )
# from user.models import Organization, User
# from researchhub_document.models import (
#     ResearchhubUnifiedDocument
# )
# from discussion.models import (
#     Thread,
# )
# from reputation.models import Contribution


# class PeerReviewViewTests(APITestCase):
#     def setUp(self):
#         moderator = create_moderator(first_name='moderator', last_name='moderator')
#         self.author = create_random_default_user('regular_user')
#         self.peer_reviewer = create_random_default_user('peer_reviewer')

#         # Create org
#         self.client.force_authenticate(moderator)
#         response = self.client.post('/api/organization/', {'name': 'test org'})
#         self.org = response.data

#         # Create review
#         self.review_request_for_author = create_peer_review_request(
#             requested_by_user=self.author,
#             organization=Organization.objects.get(id=self.org['id']),
#             title='Some random post title',
#             body='some text',
#         )

#         # Invite user
#         invite_response = self.client.post("/api/peer_review_invites/invite/",{
#             'recipient': self.peer_reviewer.id,
#             'peer_review_request': self.review_request_for_author.id,
#         })

#         # Retrieve request + details
#         self.client.force_authenticate(self.peer_reviewer)
#         response = self.client.post(f'/api/peer_review_invites/{invite_response.data["id"]}/accept/')
#         self.peer_review = response.data['peer_review']



#     def test_author_can_create_thread(self):
#         unified_doc = ResearchhubUnifiedDocument.objects.get(
#             id=self.peer_review['unified_document'],
#         )
#         author = self.review_request_for_author.requested_by_user

#         self.client.force_authenticate(author)
#         response = self.client.post(f'/api/peer_review/{self.peer_review["id"]}/discussion/?source=researchhub&is_removed=False&',{
#             'plain_text': "some text",
#             'peer_review': self.peer_review['id'],
#             'text': {'ops': [{'insert': 'some text\n'}]},
#         })

#         t = Thread.objects.get(id=response.data['id'])

#         self.assertEqual(
#             response.data['plain_text'],
#             "some text"
#         )
#         self.assertEqual(
#             t.peer_review_id,
#             self.peer_review["id"],
#         )

#     def test_reviewer_can_create_thread(self):
#         print('to implement')

#     def test_outsider_user_cannot_create_thread(self):
#         print('to implement')

#     def test_peer_reviewer_can_create_peer_review_decision(self):
#         unified_doc = ResearchhubUnifiedDocument.objects.get(
#             id=self.peer_review['unified_document'],
#         )

#         self.client.force_authenticate(self.peer_reviewer)
#         response = self.client.post(f'/api/peer_review/{self.peer_review["id"]}/create_decision/',{
#             'decision': "CHANGES_REQUESTED",
#             'discussion': {
#                 'plain_text': "some text",
#                 'text': {'ops': [{'insert': 'some text\n'}]},
#             }
#         })

#         self.assertEqual(
#             self.peer_review["id"],
#             response.data['peer_review']['id'],
#         )

#         self.assertEqual(
#             self.peer_review["id"],
#             response.data['discussion_thread']['peer_review'],
#         )

#     def test_author_cannot_create_peer_review_decision(self):
#         unified_doc = ResearchhubUnifiedDocument.objects.get(
#             id=self.peer_review['unified_document'],
#         )

#         self.client.force_authenticate(self.author)
#         response = self.client.post(f'/api/peer_review/{self.peer_review["id"]}/create_decision/',{
#             'decision': "CHANGES_REQUESTED",
#             'discussion': {
#                 'plain_text': "some text",
#                 'text': {'ops': [{'insert': 'some text\n'}]},
#             }
#         })

#         self.assertEqual(
#             response.status_code,
#             403,
#         )

#     def test_creating_peer_review_decision_creates_contribution(self):
#         unified_doc = ResearchhubUnifiedDocument.objects.get(
#             id=self.peer_review['unified_document'],
#         )

#         self.client.force_authenticate(self.peer_reviewer)
#         response = self.client.post(f'/api/peer_review/{self.peer_review["id"]}/create_decision/',{
#             'decision': "CHANGES_REQUESTED",
#             'discussion': {
#                 'plain_text': "some text",
#                 'text': {'ops': [{'insert': 'some text\n'}]},
#             }
#         })

#         contrib = Contribution.objects.get(
#             object_id=response.data['id'],
#             contribution_type=Contribution.PEER_REVIEWER,
#         )

#         self.assertTrue(contrib)

#     def test_peer_review_timeline_has_decisions(self):
#         unified_doc = ResearchhubUnifiedDocument.objects.get(
#             id=self.peer_review['unified_document'],
#         )

#         self.client.force_authenticate(self.peer_reviewer)
#         decision_response = self.client.post(f'/api/peer_review/{self.peer_review["id"]}/create_decision/',{
#             'decision': "CHANGES_REQUESTED",
#             'discussion': {
#                 'plain_text': "some text",
#                 'text': {'ops': [{'insert': 'some text\n'}]},
#             }
#         })

#         timeline_response = self.client.get(f'/api/peer_review/{self.peer_review["id"]}/timeline/')

#         self.assertEqual(
#             decision_response.data['id'],
#             timeline_response.data['results'][0]['source']['id'],
#         )
