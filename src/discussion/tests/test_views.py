from django.test import TestCase
from rest_framework.test import APIRequestFactory

from discussion.views import get_thread_id_from_path


class DiscussionViewsTests(TestCase):

    def test_get_thread_id_from_path(self):
        factory = APIRequestFactory()

        request = factory.get('/api/paper/1/discussion/1/comments')
        thread_id = get_thread_id_from_path(request)

        request = factory.get('/api/paper/1/discussion/2/comments')
        thread_id_2 = get_thread_id_from_path(request)

        request = factory.get('/api/paper/43291/discussion/300/comments')
        thread_id_3 = get_thread_id_from_path(request)

        request = factory.get('/api/paper/0/discussion/004/comments')
        thread_id_4 = get_thread_id_from_path(request)

        self.assertEqual(thread_id, 1)
        self.assertEqual(thread_id_2, 2)
        self.assertEqual(thread_id_3, 300)
        self.assertEqual(thread_id_4, 4)
