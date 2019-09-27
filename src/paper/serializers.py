import rest_framework.serializers as serializers

from .models import Paper
from user.models import User
from user.serializers import AuthorSerializer
from summary.serializers import SummarySerializer 

class PaperSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    summary = serializers.SerializerMethodField()
    authors = serializers.SerializerMethodField()
    class Meta:
        fields = "__all__"
        model = Paper

    def get_summary(self, obj):
        summary_queryset = obj.summary.filter(current=True)
        summary = {}
        if summary_queryset:
            summary = SummarySerializer(summary_queryset.first()).data
        return summary

    def get_authors(self, obj):
        authors_queryset = obj.authors.all()
        authors = []
        if authors_queryset:
            authors = AuthorSerializer(authors_queryset, many=True).data
        return authors