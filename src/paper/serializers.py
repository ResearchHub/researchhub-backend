import rest_framework.serializers as serializers

from .models import Paper
from discussion.serializers import ThreadSerializer
from summary.serializers import SummarySerializer
from user.models import User
from user.serializers import UserSerializer
from user.serializers import AuthorSerializer
from hub.serializers import HubSerializer

class PaperSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()
    discussion = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    hubs = serializers.SerializerMethodField()

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
        count = 0
        threads = []

        threads_queryset = obj.threads.all().order_by('-created_date')
        if threads_queryset:
            AMOUNT = 10
            count = len(threads_queryset)
            threads_queryset = threads_queryset[:AMOUNT]
            threads = ThreadSerializer(threads_queryset, many=True).data

        return {'count': count, 'threads': threads}

    def get_summary(self, obj):
        return SummarySerializer(obj.summary).data
    
    def get_hubs(self, obj):
        return HubSerializer(obj.hubs, many=True).data