from unittest import skip
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
        response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/',{
            'score': 7,
        })

        self.assertEqual(response.data['score'], 7)

    def test_update_review(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/',{
            'score': 7,
        })

        id = create_response.data['id']
        response = self.client.put(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/{id}/',{
            'score': 4,
        })

        print(response)
        print(response.data)
        self.assertEqual(response.data['score'], 4)

    def test_create_review_with_discussion(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/create_review/',{
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

        self.assertIn('id', response.data['review'])
        self.assertIn('id', response.data['thread'])

    def test_create_review_without_discussion(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/create_review/',{
            'review': {
                'score': 3,
            },
        })

        self.assertIn('id', response.data['review'])
        self.assertNotIn('id', response.data['thread'])

    def test_discussion_list_includes_review_data(self):
        self.client.force_authenticate(self.user)
        
        # Create review
        review_response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/create_review/',{
            'review': {
                'score': 7,
            },
            'discussion': {
                'plain_text': "review text",
                'paper': self.paper.id,
                'text': {'ops': [{'insert': 'review text'}]},
            }
        })

        response = self.client.get(f'/api/paper/{self.paper.id}/discussion/?page=1&ordering=-score&source=researchhub&is_removed=False&')

        self.assertEqual(
            response.data['results'][0]['review']['id'],
            review_response.data['review']['id'],
        )

    @skip
    def test_author_can_update_review_data(self):
        self.client.force_authenticate(self.user)

        # Create review
        create_response = self.client.post(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/create_review/',{
            'review': {
                'score': 7,
            },
            'discussion': {
                'plain_text': "review text",
                'paper': self.paper.id,
                'text': {'ops': [{'insert': 'review text'}]},
            }
        })

        # update review
        review = create_response.data['review']
        update_response = self.client.put(f'/api/researchhub_unified_documents/{self.paper.unified_document.id}/review/{review["id"]}/update_review',{
            'review': {
                'score': 3,
            },
            'discussion': {
                'plain_text': "updated",
                'paper': self.paper.id,
                'text': {'ops': [{'insert': 'updated'}]},
            }
        })

        print('update_response', update_response)
        print('update_response', update_response.data)

        self.assertEqual(
            update_response.data['discussion']['text'],
            'updated',
        )
        self.assertEqual(
            create_response.data['discussion']['id'],
            update_response.data['discussion']['id'],
        )
