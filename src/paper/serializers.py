import rest_framework.serializers as serializers

from .models import Paper
from user.models import Author
from hub.models import Hub
from discussion.serializers import ThreadSerializer
from summary.serializers import SummarySerializer
from user.serializers import UserSerializer
from user.serializers import AuthorSerializer
from hub.serializers import HubSerializer


class PaperSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=False)
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

    def to_internal_value(self, data):
        valid_authors = []
        for author in data.getlist('authors'):
            try:
                a = Author.objects.get(id=author)
                valid_authors.append(a)
            except Author.DoesNotExist:
                print(f'Author with id {author} was not found.')
        data['authors'] = valid_authors

        valid_hubs = []
        for hub in data.getlist('hubs'):
            try:
                h = Hub.objects.get(id=hub)
                valid_hubs.append(h)
            except Hub.DoesNotExist:
                print(f'Hub with id {hub} was not found.')
        data['hubs'] = valid_hubs

        return data

    def create(self, validated_data):
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')
        paper = Paper.objects.create(**validated_data)
        paper.authors.add(*authors)
        paper.hubs.add(*hubs)
        return paper

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
