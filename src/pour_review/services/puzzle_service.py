import random
from collections import deque
from datetime import date
from itertools import permutations
from math import gcd
from typing import NamedTuple

from django.utils import timezone

from pour_review.constants import PUZZLE_TIME_ZONE
from pour_review.models import PourReviewPuzzle

MAX_FLASK_CAPACITY = 15
MAX_GENERATION_ATTEMPTS = 5000


class PuzzleRule(NamedTuple):
    flask_count: int
    target_count: int
    pars: range


# Indexed by `date.weekday()`, Monday first.
WEEKDAY_RULES = (
    PuzzleRule(flask_count=3, target_count=1, pars=range(3, 4)),
    PuzzleRule(flask_count=3, target_count=1, pars=range(4, 5)),
    PuzzleRule(flask_count=3, target_count=1, pars=range(5, 7)),
    PuzzleRule(flask_count=3, target_count=1, pars=range(7, 13)),
    PuzzleRule(flask_count=4, target_count=1, pars=range(5, 13)),
    PuzzleRule(flask_count=4, target_count=2, pars=range(5, 13)),
    PuzzleRule(flask_count=4, target_count=3, pars=range(6, 13)),
)

Amounts = tuple[int, ...]


class PuzzleService:
    """Creates the daily Pour Review puzzles and checks solutions against them."""

    def get_todays_puzzle(self) -> PourReviewPuzzle:
        """Return today's puzzle, creating it on the first request of the day."""
        today = timezone.localdate(timezone=PUZZLE_TIME_ZONE)
        puzzle = PourReviewPuzzle.objects.filter(date=today).first()
        if puzzle:
            return puzzle
        puzzle, _ = PourReviewPuzzle.objects.get_or_create(
            date=today, defaults=self._generate_puzzle(today)
        )
        return puzzle

    def is_solved_by(self, puzzle: PourReviewPuzzle, pours: list[list[int]]) -> bool:
        """Return whether replaying the pours from the start fills enough flasks."""
        amounts = self._get_starting_amounts(puzzle.flasks)
        for source, target in pours:
            if not self._can_pour(puzzle.flasks, amounts, source, target):
                return False
            amounts = self._pour(puzzle.flasks, amounts, source, target)
        return self._meets_target(amounts, puzzle.target_amount, puzzle.target_count)

    def _generate_puzzle(self, day: date) -> dict:
        """Pick a puzzle matching the day's rule, preferring ones never used before."""
        rule = WEEKDAY_RULES[day.weekday()]
        past_puzzles = PourReviewPuzzle.objects.values_list(
            "flasks", "target_amount", "target_count"
        )
        used_puzzles = {
            (tuple(flasks), target_amount, target_count)
            for flasks, target_amount, target_count in past_puzzles
        }
        generator = random.Random(day.isoformat())
        repeated_puzzle = None
        for _ in range(MAX_GENERATION_ATTEMPTS):
            flasks = sorted(
                generator.sample(range(1, MAX_FLASK_CAPACITY + 1), rule.flask_count),
                reverse=True,
            )
            if gcd(*flasks) != 1:
                continue
            target_amount = generator.randrange(1, flasks[0])
            par = self._find_par(flasks, target_amount, rule.target_count)
            if par not in rule.pars:
                continue
            puzzle = {
                "flasks": flasks,
                "target_amount": target_amount,
                "target_count": rule.target_count,
                "par": par,
            }
            if (tuple(flasks), target_amount, rule.target_count) not in used_puzzles:
                return puzzle
            repeated_puzzle = repeated_puzzle or puzzle
        return repeated_puzzle

    def _find_par(
        self, flasks: list[int], target_amount: int, target_count: int
    ) -> int | None:
        """Return the fewest pours that reach the target, or None if none can."""
        start = self._get_starting_amounts(flasks)
        pour_counts = {start: 0}
        queue = deque([start])
        while queue:
            amounts = queue.popleft()
            if self._meets_target(amounts, target_amount, target_count):
                return pour_counts[amounts]
            for source, target in permutations(range(len(flasks)), 2):
                if not self._can_pour(flasks, amounts, source, target):
                    continue
                poured = self._pour(flasks, amounts, source, target)
                if poured not in pour_counts:
                    pour_counts[poured] = pour_counts[amounts] + 1
                    queue.append(poured)
        return None

    def _get_starting_amounts(self, flasks: list[int]) -> Amounts:
        """Return the opening amounts: the largest flask full, the rest empty."""
        return (flasks[0],) + (0,) * (len(flasks) - 1)

    def _can_pour(
        self, flasks: list[int], amounts: Amounts, source: int, target: int
    ) -> bool:
        """Return whether the source flask has liquid and the target has room."""
        return (
            source != target
            and max(source, target) < len(flasks)
            and amounts[source] > 0
            and amounts[target] < flasks[target]
        )

    def _pour(
        self, flasks: list[int], amounts: Amounts, source: int, target: int
    ) -> Amounts:
        """Return the amounts after pouring until the source empties or target fills."""
        poured_amount = min(amounts[source], flasks[target] - amounts[target])
        poured = list(amounts)
        poured[source] -= poured_amount
        poured[target] += poured_amount
        return tuple(poured)

    def _meets_target(
        self, amounts: Amounts, target_amount: int, target_count: int
    ) -> bool:
        """Return whether enough flasks hold exactly the target amount."""
        return amounts.count(target_amount) >= target_count
