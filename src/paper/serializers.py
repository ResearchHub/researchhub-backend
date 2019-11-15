from django.core.files.base import ContentFile
from django.http import QueryDict
import rest_framework.serializers as serializers
from rest_framework.exceptions import ValidationError

from .models import Flag, Paper, Vote
from hub.models import Hub
from user.models import Author
from discussion.serializers import ThreadSerializer
from summary.serializers import SummarySerializer
from hub.serializers import HubSerializer
from user.serializers import AuthorSerializer, UserSerializer
from utils.http import (
    get_user_from_request,
    http_request,
    RequestMethods as methods
)
from utils.voting import calculate_score
from sentry_sdk import capture_exception, configure_scope

from researchhub.settings import ELASTICSEARCH_DSL

import base64
import json


class PaperSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=False, required=False)
    discussion = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(read_only=True)
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

        authors = []
        hubs = []

        if type(data) == QueryDict:
            authors = data.getlist('authors')
            hubs = data.getlist('hubs')
        else:
            authors = data.get('authors')
            hubs = data.get('hubs')

        valid_authors = []
        for author in authors:
            try:
                a = Author.objects.get(id=author)
                valid_authors.append(a)
            except Author.DoesNotExist:
                print(f'Author with id {author} was not found.')
        data['authors'] = valid_authors

        valid_hubs = []
        for hub in hubs:
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
        file = validated_data.pop('file')

        validated_data['uploaded_by'] = self.context['request'].user
        paper = super(PaperSerializer, self).create(validated_data)

        # TODO: Add file indexing

        if (type(file) is str):
            self.check_url_contains_pdf(file)

            paper.url = file

            pdf = self._get_pdf_from_url(file)
            filename = file.split('/').pop()
            paper.file.save(filename, pdf)
        else:
            paper.file = file

        paper.authors.add(*authors)
        paper.hubs.add(*hubs)
        paper.save()

        return paper

    def update(self, instance, validated_data):
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')

        paper = super(PaperSerializer, self).update(instance, validated_data)

        # TODO: Reindex the pdf if file changes

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

    def check_url_contains_pdf(self, url):
        try:
            r = http_request(methods.HEAD, url)
            content_type = r.headers.get('content-type')
        except Exception as e:
            raise ValidationError(f'Request to {url} failed: {e}')

        if 'application/pdf' not in content_type:
            raise ValueError(
                f'Did not find content type application/pdf at {url}'
            )
        else:
            return True

    def _get_pdf_from_url(self, url):
        response = http_request(methods.GET, url)
        pdf = ContentFile(response.content)
        return pdf


def index_pdf(base64_file, paper, serialized_paper):
    """
    Indexes PDF in elastic search
    """
    es_host = ELASTICSEARCH_DSL.get('default').get('hosts')
    data = {
        "filename": "{}.pdf".format(paper.title),
        "data": base64_file.decode('utf-8')
    }
    headers = {
        'Content-Type': 'application/json'
    }

    try:
        re = requests.put(
            es_host + '/papers/_doc/{}?pipeline=pdf'.format(paper.id),
            data=json.dumps(data),
            headers=headers
        )
        if not re.ok:
            with configure_scope() as scope:
                for k in serialized_paper:
                    scope.set_extra(k, serialized_paper[k])
                scope.set_extra('req_error', re.text)
                capture_exception('Paper index failed')
    except Exception as e:
        print('Unable to index pdf:', e)


class BookmarkSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    bookmarks = PaperSerializer(many=True)


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
