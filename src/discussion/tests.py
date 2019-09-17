import json

from django.test import TestCase, Client
from django.contrib.sites.models import Site
from django_comments.models import Comment

from .models import Thread
from utils.test_helpers import TestHelper

class BaseTestCase(TestCase, TestHelper):
    site = Site.objects.get_current()

    thread_title = 'Thread Comment Title'
    thread_comment_text = 'This is a thread comment.'

    def create_thread_comment(self, user, title, comment_text):
        thread = Thread.objects.create(title=title)
        thread_comment = Comment.objects.create(
            content_object=thread,
            site=self.site,
            user=user,
            comment=comment_text
        )
        return thread_comment
    
    def create_default_thread_comment(self):
        user = self.create_user()
        title = self.thread_title
        comment_text = self.thread_comment_text
        thread = self.create_thread_comment(user, title, comment_text)
        return thread
    

class ThreadTests(BaseTestCase):

    def test_string_representation(self):
        thread = self.create_default_thread_comment()
        self.assertEqual(str(thread), 'This is a thread comment....')
