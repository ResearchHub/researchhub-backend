from rest_framework.test import APITestCase
from discussion.tests.helpers import (
    create_paper,
)
from user.tests.helpers import create_random_authenticated_user


class ReviewViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('discussion_views')
        self.paper = create_paper(uploaded_by=self.user)
    
    def test_create_review(self):
        self.client.force_authenticate(self.user)
        print(self.paper.unified_document.id)
        print(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/')
        response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/',{
            'review': {
                'score': 7,
            },
            'discussion': {
                'plain_text': "review text",
                'paper': self.paper.id,
                'text': {'ops': [{'insert': 'review text'}]},
            }
        })

        print(response)
        print(response.data)

        # self.assertIn('id', response.data['review'])
        # self.assertEqual(response.data['review']['score'], 7)

    def test_discussion_list_includes_review_data(self):
        self.client.force_authenticate(self.user)
        review_response = self.client.post(f'/api/paper/{self.paper.id}/discussion/?source=researchhub&is_removed=False&discussion_type=REVIEW',{
            'score': 7,
            'plain_text': "review text",
            'paper': self.paper.id,
            'text': {'ops': [{'insert': 'review text'}]},
        })

        response = self.client.get(f'/api/paper/{self.paper.id}/discussion/?page=1&ordering=-score&source=researchhub&is_removed=False&')

        self.assertEqual(
            response.data['results'][0]['review']['id'],
            review_response.data['review']['id'],
        )

    def test_creates_non_review_comment(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.id}/discussion/?source=researchhub&is_removed=False',{
            'plain_text': "some text",
            'paper': self.paper.id,
            'text': {'ops': [{'insert': 'some text'}]},
        })

        self.assertEqual(
            None,
            response.data['review'],
        )
