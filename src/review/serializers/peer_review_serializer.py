import rest_framework.serializers as serializers
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import ModelSerializer

from review.models.peer_review_model import PeerReview


class PeerReviewSerializer(ModelSerializer):
    user = serializers.SerializerMethodField()

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

    def get_user(self, obj):
        user = obj.user

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "author_profile": {
                "id": user.author_profile.id,
                # "profile_image": profile_image,
                "first_name": user.author_profile.first_name,
                "last_name": user.author_profile.last_name,
            },
        }

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
