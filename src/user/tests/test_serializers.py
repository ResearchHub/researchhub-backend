from django.test import TestCase

from .helpers import create_author, create_user
from oauth.tests.helpers import create_social_account
from user.models import Author, User
from user.serializers import AuthorSerializer


class UserSerializersTests(TestCase):

    def setUp(self):
        self.user = create_user(first_name='Serializ')

    def test_author_serializer(self):
        pass
        # create_social_account(user=self.user, provider='google')
        # serialized = AuthorSerializer(self.user.author).data
        # self.assertEqual(serialized.profile_image, self.author.profile_image)
