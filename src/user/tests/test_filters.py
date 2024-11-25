from django.test import TestCase

from user.filters import AuthorFilter
from user.related_models.author_model import Author


class AuthorFilterTests(TestCase):

    def test_filter_by_id__ne(self):
        # Arrange
        user1 = Author.objects.create()
        user2 = Author.objects.create()
        user3 = Author.objects.create()

        queryset = Author.objects.all()

        # Act
        filter_instance = AuthorFilter(
            data={"id__ne": f"{user1.id},{user2.id}"}, queryset=queryset
        )

        # Assert
        self.assertEqual(len(filter_instance.qs), queryset.count() - 2)
        self.assertNotIn(user1, filter_instance.qs)
        self.assertNotIn(user2, filter_instance.qs)
        self.assertIn(user3, filter_instance.qs)

    def test_filter_by_id__ne_without_matches(self):
        # Arrange
        user1 = Author.objects.create()
        user2 = Author.objects.create()
        user3 = Author.objects.create()

        # restrict the queryset to only include user1 and user2
        queryset = Author.objects.filter(id__in=[user1.id, user2.id])

        # Act
        filter_instance = AuthorFilter(data={"id__ne": user3.id}, queryset=queryset)

        # Assert
        self.assertEqual(len(filter_instance.qs), queryset.count())
        self.assertIn(user1, filter_instance.qs)
        self.assertIn(user2, filter_instance.qs)

    def test_filter_by_first_name(self):
        # Arrange
        Author.objects.create(first_name="firstName1")
        user2 = Author.objects.create(first_name="firstName2")
        Author.objects.create(first_name="firstName3")

        queryset = Author.objects.all()

        # Act
        filter_instance = AuthorFilter(
            data={"first_name": "firstName2"}, queryset=queryset
        )

        # Assert
        self.assertEqual(len(filter_instance.qs), 1)
        self.assertIn(user2, filter_instance.qs)
