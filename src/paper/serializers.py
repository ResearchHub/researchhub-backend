import rest_framework.serializers as serializers

from .models import Paper
from discussion.serializers import ThreadSerializer
from summary.serializers import SummarySerializer
from user.models import User
from user.serializers import AuthorSerializer


class PaperSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()
    discussion = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    uploaded_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = '__all__'
        model = Paper

    def get_authors(self, obj):
        authors_queryset = obj.authors.all()
        authors = []
        if authors_queryset:
            authors = AuthorSerializer(authors_queryset, many=True).data
        return authors

    def get_discussion(self, obj):
        threads_queryset = obj.threads.all().order_by('-created_date')
        if threads_queryset:
            AMOUNT = 10
            count = len(threads_queryset)
            threads_queryset = threads_queryset[:AMOUNT]
            threads = ThreadSerializer(threads_queryset, many=True).data
        return {'count': count, 'threads': threads}

    def get_summary(self, obj):
        summary_queryset = obj.summary.filter(current=True)
        summary = {}
        if summary_queryset:
            summary = SummarySerializer(summary_queryset.first()).data
        return summary
