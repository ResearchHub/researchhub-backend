from datetime import date

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from pour_review.models import PourReviewPuzzle, PourReviewResult
from pour_review.services.puzzle_service import WEEKDAY_RULES
from user.tests.helpers import create_user

SOLVING_POURS = [[0, 1], [1, 2], [2, 0], [1, 2], [0, 1], [1, 2]]


class PourReviewViewsTest(APITestCase):
    def setUp(self):
        self.user = create_user()
        self.puzzle = PourReviewPuzzle.objects.create(
            date=date(2026, 1, 1),
            flasks=[8, 5, 3],
            target_amount=4,
            target_count=1,
            par=6,
        )

    def test_creates_todays_puzzle_on_first_request(self):
        """Today's puzzle is generated within its weekday's par range for anyone."""
        # Act
        response = self.client.get(reverse("pour_review:pour-review-puzzle-today"))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        puzzle = PourReviewPuzzle.objects.get(id=response.data["id"])
        self.assertIn(puzzle.par, WEEKDAY_RULES[puzzle.date.weekday()].pars)
        self.assertIsNone(response.data["stats"])

    def test_records_pours_that_solve_the_puzzle(self):
        """A solving submission is saved and returns the user's updated stats."""
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(
            reverse("pour_review:pour-review-result-list"),
            {"puzzle": self.puzzle.id, "pours": SOLVING_POURS},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["solved_pours"], SOLVING_POURS)
        self.assertEqual(response.data["stats"]["played"], 1)
        self.assertEqual(response.data["par_rate"], 100)

    def test_rejects_pours_that_do_not_solve_the_puzzle(self):
        """A submission whose pours leave no flask at the target is refused."""
        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.post(
            reverse("pour_review:pour-review-result-list"),
            {"puzzle": self.puzzle.id, "pours": SOLVING_POURS[:-1]},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PourReviewResult.objects.exists())
