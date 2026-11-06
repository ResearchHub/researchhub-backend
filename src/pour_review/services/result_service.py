from datetime import date, timedelta

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from pour_review.constants import PUZZLE_TIME_ZONE
from pour_review.models import PourReviewPuzzle, PourReviewResult
from user.models import User


class ResultService:
    """Summarizes how players have done on Pour Review puzzles."""

    def get_stats(self, user: User) -> dict:
        """Return the user's games played, streaks, and percentage of games at par."""
        results = PourReviewResult.objects.filter(user=user)
        dates = sorted(results.values_list("puzzle__date", flat=True))
        current_streak, best_streak = self._count_streaks(dates)
        return {
            "played": len(dates),
            "current_streak": current_streak,
            "best_streak": best_streak,
            "par_rate": self._calculate_par_rate(results),
        }

    def get_par_rate(self, puzzle: PourReviewPuzzle) -> int:
        """Return the percentage of the puzzle's players who matched par."""
        return self._calculate_par_rate(puzzle.results.all())

    def _calculate_par_rate(self, results: QuerySet[PourReviewResult]) -> int:
        """Return the percentage of results solved within their puzzle's par."""
        totals = results.aggregate(
            played=Count("id"),
            at_par=Count("id", filter=Q(pour_count__lte=F("puzzle__par"))),
        )
        if not totals["played"]:
            return 0
        return round(100 * totals["at_par"] / totals["played"])

    def _count_streaks(self, dates: list[date]) -> tuple[int, int]:
        """Return the current and best runs of consecutive days played."""
        best_streak = streak = 0
        previous_day = None
        for day in dates:
            streak = streak + 1 if previous_day == day - timedelta(days=1) else 1
            best_streak = max(best_streak, streak)
            previous_day = day
        today = timezone.localdate(timezone=PUZZLE_TIME_ZONE)
        if previous_day is None or today - previous_day > timedelta(days=1):
            return 0, best_streak
        return streak, best_streak
