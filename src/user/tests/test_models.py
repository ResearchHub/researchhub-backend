from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from user.related_models.follow_model import Follow
from user.related_models.user_model import User
from user.tests.helpers import create_user


class AuthorModelsTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="random@researchhub.com",
            first_name="random",
            last_name="user",
        )

        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
            is_open_access=True,
        )

        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
            is_open_access=False,
        )

        Authorship.objects.create(author=self.user.author_profile, paper=paper1)
        Authorship.objects.create(author=self.user.author_profile, paper=paper2)

    def test_citation_count_property(self):
        self.assertEqual(self.user.author_profile.citation_count, 30)

    def test_paper_count_property(self):
        self.assertEqual(self.user.author_profile.paper_count, 2)

    def test_open_access_pct_property(self):
        self.assertEqual(self.user.author_profile.open_access_pct, 0.5)

    def test_achievements(self):
        self.assertIn("CITED_AUTHOR", self.user.author_profile.achievements)


class FollowModelTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="random@researchhub.com",
            first_name="random",
            last_name="user",
        )

    def test_follow_user(self):
        # Arrange & Act
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user.id,
        )

        # Assert
        self.assertEqual(follow.user, self.user)
        self.assertEqual(follow.content_type, ContentType.objects.get_for_model(User))
        self.assertEqual(follow.object_id, self.user.id)

    def test_follow_paper(self):
        # Arrange
        paper = Paper.objects.create(title="title1", citations=10, is_open_access=True)

        # Act
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
        )

        # Assert
        self.assertEqual(follow.user, self.user)
        self.assertEqual(follow.content_type, ContentType.objects.get_for_model(Paper))
        self.assertEqual(follow.object_id, paper.id)

    def test_follow_unsupported_model(self):
        # Arrange
        with self.assertRaises(ValidationError):
            Follow.objects.create(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Authorship),
                object_id=1,
            )
