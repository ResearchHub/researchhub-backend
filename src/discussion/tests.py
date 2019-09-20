from django.test import TestCase
from django.contrib.sites.models import Site

from .models import Thread
from utils.test_helpers import IntegrationTestHelper, TestHelper


class BaseTestCase(TestCase, TestHelper):
    site = Site.objects.get_current()

    thread_title = 'Thread Title'
    thread_text = 'This is a thread.'

    def create_default_thread(self):
        paper = self.create_paper_without_authors()
        user = self.create_user()
        title = self.thread_title
        text = self.thread_text
        thread = self.create_thread(paper, user, title, text)
        return thread

    def create_thread(self, paper, user, title, text):
        thread = Thread.objects.create(
            paper=paper,
            created_by=user,
            title=title,
            text=text
        )
        return thread


class ThreadTests(BaseTestCase):

    def test_string_representation(self):
        thread = self.create_default_thread()
        self.assertEqual(
            str(thread),
            'testuser@gmail.com: Thread Title'
        )


