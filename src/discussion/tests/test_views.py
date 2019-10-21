from django.test import TestCase
from rest_framework.test import APIRequestFactory

from .helpers import (
    build_discussion_detail_url,
    create_comment,
    create_flag,
    create_paper,
    create_reply,
    create_thread
)
from discussion.views import get_thread_id_from_path
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_delete_response,
    get_authenticated_patch_response,
    get_authenticated_put_response
)


class DiscussionViewsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/'
        self.user = create_random_authenticated_user('discussion_views')
        self.paper = create_paper(uploaded_by=self.user)
        self.thread = create_thread(paper=self.paper, created_by=self.user)
        self.comment = create_comment(thread=self.thread, created_by=self.user)
        self.reply = create_reply(parent=self.comment, created_by=self.user)
        self.trouble_maker = create_random_authenticated_user('trouble_maker')

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

    def test_thread_creator_can_update_thread(self):
        text = 'update thread with patch'
        patch_response = self.get_thread_patch_response(self.user, text)
        self.assertContains(patch_response, text, status_code=200)

        text = 'update thread with put'
        put_response = self.get_thread_put_response(self.user, text)

        self.assertContains(put_response, text, status_code=200)

    def test_ONLY_thread_creator_can_update_thread(self):
        text = 'virus'
        patch_response = self.get_thread_patch_response(
            self.trouble_maker,
            text
        )
        put_response = self.get_thread_put_response(self.trouble_maker, text)

        self.assertEqual(patch_response.status_code, 403)
        self.assertEqual(put_response.status_code, 403)

    def test_comment_creator_can_update_comment(self):
        text = 'update comment with patch'
        patch_response = self.get_comment_patch_response(self.user, text)

        self.assertContains(patch_response, text, status_code=200)

        text = 'update comment with put'
        put_response = self.get_comment_put_response(self.user, text)

        self.assertContains(put_response, text, status_code=200)

    def test_ONLY_comment_creator_can_update_comment(self):
        text = 'virus'
        patch_response = self.get_comment_patch_response(
            self.trouble_maker,
            text
        )
        put_response = self.get_comment_put_response(self.trouble_maker, text)

        self.assertEqual(patch_response.status_code, 403)
        self.assertEqual(put_response.status_code, 403)

    def test_reply_creator_can_update_reply(self):
        text = 'update reply with patch'
        patch_response = self.get_reply_patch_response(self.user, text)

        self.assertContains(patch_response, text, status_code=200)

        text = 'update reply with put'
        put_response = self.get_reply_put_response(self.user, text)

        self.assertContains(put_response, text, status_code=200)

    def test_ONLY_reply_creator_can_update_reply(self):
        text = 'virus'
        patch_response = self.get_reply_patch_response(
            self.trouble_maker,
            text
        )
        put_response = self.get_reply_put_response(self.trouble_maker, text)

        self.assertEqual(patch_response.status_code, 403)
        self.assertEqual(put_response.status_code, 403)

    def test_flag_creator_can_delete_flag(self):
        user = create_random_authenticated_user('flagger')

        thread_flag = create_flag(created_by=user, item=self.thread)
        thread_response = self.get_thread_flag_delete_response(user)

        self.assertContains(
            thread_response,
            thread_flag.reason,
            status_code=200
        )

        comment_flag = create_flag(created_by=user, item=self.comment)
        comment_response = self.get_comment_flag_delete_response(user)

        self.assertContains(
            comment_response,
            comment_flag.reason,
            status_code=200
        )

        reply_flag = create_flag(created_by=user, item=self.reply)
        reply_response = self.get_reply_flag_delete_response(user)

        self.assertContains(reply_response, reply_flag.reason, status_code=200)

    def test_ONLY_flag_creator_can_delete_flag(self):
        user = create_random_authenticated_user('flagger1')

        create_flag(created_by=user, item=self.thread)
        response = self.get_thread_flag_delete_response(self.trouble_maker)
        self.assertEqual(response.status_code, 400)

        create_flag(created_by=user, item=self.comment)
        response = self.get_comment_flag_delete_response(self.trouble_maker)
        self.assertEqual(response.status_code, 400)

        create_flag(created_by=user, item=self.reply)
        response = self.get_reply_flag_delete_response(self.trouble_maker)
        self.assertEqual(response.status_code, 400)

    def get_thread_patch_response(self, user, text):
        url, data = self.get_request_config('thread', text)
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_thread_put_response(self, user, text):
        url = build_discussion_detail_url(self, 'thread')
        data = {
            'title': text,
            'text': text
        }
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_comment_patch_response(self, user, text):
        url, data = self.get_request_config('comment', text)
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_comment_put_response(self, user, text):
        url, data = self.get_request_config('comment', text)
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_reply_patch_response(self, user, text):
        url, data = self.get_request_config('reply', text)
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_reply_put_response(self, user, text):
        url = build_discussion_detail_url(self, 'reply')
        data = {
            'parent': self.comment.id,
            'text': text
        }
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_request_config(self, discussion_type, text):
        url = build_discussion_detail_url(self, discussion_type)
        data = {'text': text}
        return url, data

    def get_thread_flag_delete_response(self, user):
        url = build_discussion_detail_url(self, 'thread')
        response = self.get_flag_delete_response(user, url)
        return response

    def get_comment_flag_delete_response(self, user):
        url = build_discussion_detail_url(self, 'comment')
        response = self.get_flag_delete_response(user, url)
        return response

    def get_reply_flag_delete_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        response = self.get_flag_delete_response(user, url)
        return response

    def get_flag_delete_response(self, user, url):
        url += 'flag/'
        data = None
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
