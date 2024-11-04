from rest_framework.exceptions import ValidationError
from rest_framework.serializers import ModelSerializer

from review.models.peer_review_model import PeerReview


class PeerReviewSerializer(ModelSerializer):
    class Meta:
        model = PeerReview
        fields = (
            "id",
            # data
            "comment_thread",
            "paper",
            "status",
            "user",
            # metadata
            "created_date",
            "updated_date",
        )
        read_only_fields = (
            "id",
            "created_date",
            "updated_date",
        )

    def validate(self, attrs):
        request = self.context.get("request")

        if request.method == "POST":
            if "status" in attrs and attrs["status"] != PeerReview.Status.PENDING:
                raise ValidationError(
                    {"status": "Must be PENDING for new peer reviews."}
                )

        if request.method in ["PATCH", "PUT"]:
            if "comment_thread" not in attrs or attrs["comment_thread"] is None:
                raise ValidationError({"comment_thread": "This field is required."})
        return super().validate(attrs)
