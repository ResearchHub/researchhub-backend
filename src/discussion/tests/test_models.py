from django.test import TestCase

from discussion.tests.helpers import create_comment, create_thread
from paper.tests.helpers import create_paper
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class DiscussionModelsTests(TestCase):
    def setUp(self):
        self.paper = create_paper()
        self.thread = create_thread(paper=self.paper)
        self.comment = create_comment(thread=self.thread)

    def test_thread_parent_is_paper(self):
        self.assertEqual(self.thread.parent, self.paper)

    def test_comment_paper_property(self):
        self.assertEqual(self.comment.paper, self.paper)

    def test_thread_users_to_notify_includes_paper_authors(self):
        user_1 = create_random_default_user("Amy")
        user_2 = create_random_default_user("Bamy")
        self.paper.authors.add(user_1.author_profile)
        self.paper.authors.add(user_2.author_profile)
        self.assertTrue(user_1 in self.thread.users_to_notify)
        self.assertTrue(user_2 in self.thread.users_to_notify)

    def test_thread_users_to_notify_exlcudes_non_author_creator(self):
        user = create_random_default_user("Non-author")
        thread = create_thread(paper=self.paper, created_by=user)
        self.assertFalse(user in thread.users_to_notify)

    def test_comment_users_to_notify_includes_thread_creator(self):
        user = create_random_default_user("Eamy")
        thread = create_thread(created_by=user)
        comment = create_comment(thread=thread)
        self.assertTrue(user in comment.users_to_notify)

    def test_comment_users_to_notify_exlcudes_comment_creator(self):
        user = create_random_default_user("Famy")
        comment = create_comment(thread=self.thread, created_by=user)
        self.assertFalse(user in comment.users_to_notify)

    def test_creating_thread_notifies_paper_submitter(self):
        submitter = create_random_default_user("Submitter")
        commenter = create_random_default_user("Commenter")
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=commenter)
        self.assertTrue(submitter in thread.users_to_notify)

    def test_creating_comment_notifies_paper_submitter(self):
        submitter = create_random_default_user("Submitter")
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread)
        self.assertTrue(submitter in comment.users_to_notify)

    def test_thread_creator_not_receive_notification_on_own_contribution(self):
        submitter = create_random_default_user("Submitter")
        commenter = create_random_default_user("Commenter")
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=commenter)
        self.assertFalse(commenter in thread.users_to_notify)

    def test_comment_creator_not_receive_notification_on_own_contribution(self):
        submitter = create_random_default_user("Submitter")
        thread_creator = create_random_default_user("ThreadCreator")
        comment_creator = create_random_default_user("Commenter")
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=thread_creator)
        comment = create_comment(thread=thread, created_by=comment_creator)
        self.assertFalse(comment_creator in comment.users_to_notify)

    def test_creating_thread_notifies_post_creator(self):
        creator = create_random_default_user("Creator")
        thread_creator = create_random_default_user("ThreadCreator")
        post = create_post(created_by=creator)
        thread = create_thread(post=post, created_by=thread_creator)
        self.assertTrue(creator in thread.users_to_notify)

    def test_creating_comment_notifies_post_creator(self):
        creator = create_random_default_user("Creator")
        thread_creator = create_random_default_user("ThreadCreator")
        comment_creator = create_random_default_user("Commenter")
        post = create_post(created_by=creator)
        thread = create_thread(post=post, created_by=thread_creator)
        comment = create_comment(thread=thread, created_by=comment_creator)
        self.assertTrue(creator in comment.users_to_notify)

    def test_submitter_who_also_creates_a_thread_should_not_receive_notifications(self):
        submitter = create_random_default_user("Submitter")
        thread_creator = create_random_default_user("ThreadCreator")

        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=submitter)

        self.assertTrue(submitter not in thread.users_to_notify)

    def test_creating_thread_should_not_notify_thread_creator(self):
        submitter = create_random_default_user("Submitter")
        thread_creator = create_random_default_user("ThreadCreator")

        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=submitter)

        self.assertTrue(thread_creator not in thread.users_to_notify)

    def test_creating_comment_should_not_notify_comment_creator(self):
        submitter = create_random_default_user("Submitter")
        thread_creator = create_random_default_user("ThreadCreator")
        comment_creator = create_random_default_user("Commenter")

        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=thread_creator)
        comment = create_comment(thread=thread, created_by=comment_creator)

        self.assertTrue(comment_creator not in comment.users_to_notify)
        self.assertTrue(thread_creator in comment.users_to_notify)
