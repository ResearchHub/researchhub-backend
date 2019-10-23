import rest_framework.serializers as serializers

from .models import Flag, Paper, Vote
from hub.models import Hub
from user.models import Author
from discussion.serializers import ThreadSerializer
from summary.serializers import SummarySerializer
from hub.serializers import HubSerializer
from user.serializers import AuthorSerializer, UserSerializer
from utils.http import get_user_from_request
from utils.voting import calculate_score


class PaperSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=False)
    discussion = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    user_vote = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        read_only_fields = [
            'score',
            'user_vote'
        ]
        model = Paper

    def to_internal_value(self, data):
        data = data.copy()
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

        paper = super(PaperSerializer, self).create(validated_data)

        paper.authors.add(*authors)
        paper.hubs.add(*hubs)

        return paper

    def update(self, instance, validated_data):
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')

        paper = super(PaperSerializer, self).update(instance, validated_data)

        instance.authors.add(*authors)
        instance.hubs.add(*hubs)

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
        request = self.context.get('request')

        threads_queryset = obj.threads.all().order_by('-created_date')
        if threads_queryset:
            AMOUNT = 20
            count = len(threads_queryset)
            threads_queryset = threads_queryset[:AMOUNT]
            threads = ThreadSerializer(
                threads_queryset,
                many=True,
                context={'request': request}
            ).data

        return {'count': count, 'threads': threads}

    def get_summary(self, obj):
        return SummarySerializer(obj.summary).data

    def get_hubs(self, obj):
        return HubSerializer(obj.hubs, many=True).data

    def get_score(self, obj):
        score = calculate_score(obj, Vote.UPVOTE, Vote.DOWNVOTE)
        return score

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = obj.votes.get(created_by=user.id)
                vote = VoteSerializer(vote).data
            except Vote.DoesNotExist:
                pass
        return vote


class FlagSerializer(serializers.ModelSerializer):

    class Meta:
        fields = [
            'created_by',
            'created_date',
            'paper',
            'reason',
        ]
        model = Flag


class VoteSerializer(serializers.ModelSerializer):

    class Meta:
        fields = [
            'created_by',
            'created_date',
            'vote_type',
            'paper',
        ]
        model = Vote

        fields.append('authors__id')
