from django.test import TestCase

from utils.test_helpers import TestHelper, create_paper


class SignalTests(TestCase, TestHelper):

    def setUp(self):
        pass

    def test_create_paper_increases_rep_by_1(self):
        unique_value = 'Ronald Weasley'
        user = self.create_random_default_user(unique_value)
        create_paper(uploaded_by=user)
        self.assertEqual(user.reputation, 2)
