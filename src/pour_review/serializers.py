from rest_framework import serializers

from pour_review.constants import LAUNCH_DATE
from pour_review.models import PourReviewPuzzle, PourReviewResult
from pour_review.services.puzzle_service import PuzzleService
from pour_review.services.result_service import ResultService


class PuzzleSerializer(serializers.ModelSerializer):
    number = serializers.SerializerMethodField()
    par_rate = serializers.SerializerMethodField()
    solved_pours = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = PourReviewPuzzle
        fields = [
            "id",
            "number",
            "date",
            "flasks",
            "target_amount",
            "target_count",
            "par",
            "par_rate",
            "solved_pours",
            "stats",
        ]

    def get_number(self, puzzle: PourReviewPuzzle) -> int:
        """Return the puzzle's issue number, counting launch day as the first."""
        return (puzzle.date - LAUNCH_DATE).days + 1

    def get_par_rate(self, puzzle: PourReviewPuzzle) -> int:
        """Return the percentage of today's players who matched par."""
        return ResultService().get_par_rate(puzzle)

    def get_solved_pours(self, puzzle: PourReviewPuzzle) -> list[list[int]] | None:
        """Return the signed-in user's winning pours, if they solved the puzzle."""
        user = self.context["request"].user
        if not user.is_authenticated:
            return None
        result = puzzle.results.filter(user=user).first()
        return result.pours if result else None

    def get_stats(self, puzzle: PourReviewPuzzle) -> dict | None:
        """Return the signed-in user's lifetime stats."""
        user = self.context["request"].user
        return ResultService().get_stats(user) if user.is_authenticated else None


class ResultSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    pours = serializers.ListField(
        child=serializers.ListField(
            child=serializers.IntegerField(min_value=0), min_length=2, max_length=2
        )
    )

    class Meta:
        model = PourReviewResult
        fields = ["user", "puzzle", "pours"]

    def validate(self, attrs: dict) -> dict:
        """Reject pours that break the rules or leave the puzzle unsolved."""
        if not PuzzleService().is_solved_by(attrs["puzzle"], attrs["pours"]):
            raise serializers.ValidationError(
                {"pours": "These pours do not solve the puzzle."}
            )
        return attrs

    def create(self, validated_data: dict) -> PourReviewResult:
        """Save the result with its pour count."""
        validated_data["pour_count"] = len(validated_data["pours"])
        return super().create(validated_data)

    def to_representation(self, result: PourReviewResult) -> dict:
        """Return the solved puzzle with the user's refreshed stats."""
        return PuzzleSerializer(result.puzzle, context=self.context).data
