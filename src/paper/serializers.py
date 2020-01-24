from django.core.files.base import ContentFile
from django.db import transaction
from django.http import QueryDict
from rest_framework.exceptions import ValidationError
import rest_framework.serializers as serializers

from discussion.serializers import ThreadSerializer
from hub.models import Hub
from hub.serializers import HubSerializer
from paper.exceptions import PaperSerializerError
from paper.models import Flag, Paper, Vote
from summary.serializers import SummarySerializer
from user.models import Author
from user.serializers import AuthorSerializer, UserSerializer
from utils.http import (
    get_user_from_request,
    http_request,
    RequestMethods as methods
)
import utils.sentry as sentry
from utils.voting import calculate_score


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
        data = self._transform_to_dict(data)
        data = self._copy_data(data)

        # TODO: Refactor below

        valid_authors = []
        for author_id in data['authors']:
            if isinstance(author_id, Author):
                author_id = author_id.id

            try:
                author = Author.objects.get(pk=author_id)
                valid_authors.append(author)
            except Author.DoesNotExist:
                print(f'Author with id {author_id} was not found.')
        data['authors'] = valid_authors

        valid_hubs = []
        for hub_id in data['hubs']:
            if isinstance(hub_id, Hub):
                hub_id = hub_id.id

            try:
                hub = Hub.objects.get(pk=hub_id)
                valid_hubs.append(hub)
            except Hub.DoesNotExist:
                print(f'Hub with id {hub_id} was not found.')
        data['hubs'] = valid_hubs

        return data

    def _transform_to_dict(self, obj):
        if isinstance(obj, QueryDict):
            authors = obj.getlist('authors', [])
            hubs = obj.getlist('hubs', [])
            obj = obj.dict()
            obj['authors'] = authors
            obj['hubs'] = hubs
        return obj

    def _copy_data(self, data):
        """Returns a copy of `data`.

        This is a helper method used to handle files which, when present in the
        data, prevent `.copy()` from working.

        Args:
            data (dict)
        """
        file = None
        try:
            file = data.pop('file')
        except KeyError:
            pass

        data = data.copy()
        data['file'] = file
        return data

    def create(self, validated_data):
        validated_data['uploaded_by'] = self.context['request'].user

        # Prepare validated_data by removing m2m and file for now
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')
        file = validated_data.pop('file')
        try:
            with transaction.atomic():
                paper = super(PaperSerializer, self).create(validated_data)

                # Now add m2m values properly
                paper.authors.add(*authors)
                paper.hubs.add(*hubs)

                self._add_file(paper, file)

                paper.save(update_fields=['file'])  # m2m fields not allowed
                return paper
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to created paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )

    def update(self, instance, validated_data):
        authors = validated_data.pop('authors', [None])
        hubs = validated_data.pop('hubs', [None])
        file = validated_data.pop('file', None)

        update_fields = [field for field in validated_data]

        try:
            with transaction.atomic():
                paper = super(PaperSerializer, self).update(
                    instance,
                    validated_data
                )

                current_hubs = paper.hubs.all()
                remove_hubs = []
                for current_hub in current_hubs:
                    if current_hub not in hubs:
                        remove_hubs.append(current_hub)
                paper.hubs.remove(*remove_hubs)
                paper.authors.add(*authors)
                paper.hubs.add(*hubs)

                if file:
                    update_fields.append('file')
                    self._add_file(paper, file)

                # m2m fields not allowed in update_fields
                paper.save(update_fields=update_fields)
                return paper
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to created paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )

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

        try:
            threads_queryset = obj.thread_obj
        except AttributeError:
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
                vote_created_by = obj.vote_created_by
                if len(vote_created_by) == 0:
                    return None
                vote = VoteSerializer(vote_created_by).data
            except AttributeError:
                try:
                    vote = obj.votes.get(created_by=user.id)
                    vote = VoteSerializer(vote).data
                except Vote.DoesNotExist:
                    pass
        return vote

    def _add_file(self, paper, file):
        if (type(file) is str):
            self._check_url_contains_pdf(file)

            paper.url = file

            pdf = self._get_pdf_from_url(file)
            filename = file.split('/').pop()
            paper.file.save(filename, pdf)
        else:
            paper.file = file

    def _check_url_contains_pdf(self, url):
        try:
            r = http_request(methods.HEAD, url, timeout=3)
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
        response = http_request(methods.GET, url, timeout=3)
        pdf = ContentFile(response.content)
        return pdf


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
    paper = PaperSerializer()
    
    class Meta:
        fields = [
            'created_by',
            'created_date',
            'vote_type',
            'paper',
        ]
        model = Vote
