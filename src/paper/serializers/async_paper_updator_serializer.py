from rest_framework.serializers import ModelSerializer

from paper.related_models.async_paper_updator_model import AsyncPaperUpdator


class AsyncPaperUpdatorSerializer(ModelSerializer):
    class Metea:
        model = AsyncPaperUpdator
        fields = "__all__"
