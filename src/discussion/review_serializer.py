from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from discussion.related_models import Review
from researchhub.serializers import DynamicModelFieldSerializer


class ReviewSerializer(ModelSerializer):
    class Meta:
        model = Review
        fields = [
            'id',
            'score',
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