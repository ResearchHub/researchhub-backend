from rest_framework.serializers import ModelSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from review.models import Review


class ReviewSerializer(ModelSerializer):
    class Meta:
        model = Review
        fields = [
            'id',
            'score',
            'created_by',
            'unified_document',
            'is_removed',
        ]
        read_only_fields = [
            'created_date',
            'updated_date',
        ]

class DynamicReviewSerializer(
    DynamicModelFieldSerializer,
):
    class Meta:
        model = Review
        fields = '__all__'