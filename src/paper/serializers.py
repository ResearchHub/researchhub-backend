from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import QueryDict
import rest_framework.serializers as serializers

from .utils import check_user_pdf_title
from discussion.serializers import ThreadSerializer
from hub.models import Hub
from hub.serializers import HubSerializer
from paper.exceptions import PaperSerializerError
from paper.models import Flag, Paper, Vote, Figure
from paper.tasks import download_pdf, add_references
from summary.serializers import SummarySerializer
from user.models import Author
from user.serializers import AuthorSerializer, UserSerializer
from utils.http import get_user_from_request
import utils.sentry as sentry

from researchhub.settings import PAGINATION_PAGE_SIZE, TESTING


class PaperSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=False, required=False)
    discussion = serializers.SerializerMethodField()
    discussion_count = serializers.SerializerMethodField()
    hubs = HubSerializer(many=True, required=False)
    referenced_by = serializers.SerializerMethodField()
    references = serializers.PrimaryKeyRelatedField(read_only=True, many=True)
    score = serializers.SerializerMethodField()
    summary = SummarySerializer(required=False)
    uploaded_by = UserSerializer(read_only=True)
    user_vote = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        read_only_fields = [
            'referenced_by'
            'references',
            'score',
            'user_vote',
            'user_flag',
            'users_who_bookmarked',
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
        user = self.context['request'].user
        validated_data['uploaded_by'] = user

        # Prepare validated_data by removing m2m and file for now
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')
        file = validated_data.pop('file')
        user_title = validated_data.pop('paper_title')
        try:
            with transaction.atomic():
                paper = super(PaperSerializer, self).create(validated_data)

                # self._check_pdf_title(user_title, file)

                Vote.objects.create(
                    paper=paper,
                    created_by=user,
                    vote_type=Vote.UPVOTE
                )

                # Now add m2m values properly
                paper.authors.add(*authors)
                paper.hubs.add(*hubs)

                try:
                    self._add_file(paper, file)
                except Exception as e:
                    sentry.log_error(
                        e,
                    )

                self._add_references(paper)

                return paper
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to created paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )
            raise error

    def update(self, instance, validated_data):
        authors = validated_data.pop('authors', [None])
        hubs = validated_data.pop('hubs', [None])
        file = validated_data.pop('file', None)

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
                    self._add_file(paper, file)

                return paper
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to created paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )
            raise error

    def get_discussion(self, obj):
        request = self.context.get('request')
        serializer = self.context.get('thread_serializer', ThreadSerializer)

        threads_queryset = obj.threads.all()
        threads = serializer(
            threads_queryset.order_by('-created_date')[:PAGINATION_PAGE_SIZE],
            many=True,
            context={'request': request}
        )

        return {'count': threads_queryset.count(), 'threads': threads.data}

    def get_discussion_count(self, obj):
        return obj.get_discussion_count()

    def get_referenced_by(self, obj):
        serialized = PaperSerializer(
            obj.referenced_by,
            many=True,
            context=self.context
        )
        return serialized.data

    def get_score(self, obj):
        return obj.calculate_score()

    def get_user_vote(self, obj):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote_created_by = obj.vote_created_by
                if len(vote_created_by) == 0:
                    return None
                vote = PaperVoteSerializer(vote_created_by).data
            except AttributeError:
                try:
                    vote = obj.votes.get(created_by=user.id)
                    vote = PaperVoteSerializer(vote).data
                except Vote.DoesNotExist:
                    pass
        return vote

    def get_user_flag(self, paper):
        flag = None
        user = get_user_from_request(self.context)
        if user:
            try:
                flag_created_by = paper.flag_created_by
                if len(flag_created_by) == 0:
                    return None
                flag = FlagSerializer(flag_created_by).data
            except AttributeError:
                try:
                    flag = paper.flags.get(created_by=user.id)
                    flag = FlagSerializer(flag).data
                except Flag.DoesNotExist:
                    pass
        return flag

    def _add_references(self, paper):
        try:
            if not TESTING:
                add_references.apply_async((paper.id,), priority=5, countdown=10)
            else:
                add_references(paper.id)
        except Exception as e:
            print(e)

    def _add_file(self, paper, file):
        if (type(file) is str):
            try:
                URLValidator()(file)
            except (ValidationError, Exception) as e:
                print(e)
            else:
                paper.url = file
                paper.file = None
                paper.save()
        elif file is not None:
            paper.file = file
            paper.save(update_fields=['file'])
            return

        if paper.url is not None:
            if not TESTING:
                download_pdf.apply_async((paper.id,), priority=3)
            else:
                download_pdf(paper.id)

    def _check_pdf_title(self, user_title, file):
        if type(file) is str:
            try:
                URLValidator()(file)
            except (ValidationError, Exception) as e:
                print(e)
                raise e

            # Download the file and check the title
            pdf, _ = download_pdf(file)
            self._check_title_in_pdf(user_title, pdf)
        else:
            self._check_title_in_pdf(user_title, file)

    def _check_title_in_pdf(self, user_title, file):
        title_in_pdf = check_user_pdf_title(user_title, file)
        if not title_in_pdf:
            e = Exception('User entered title not in pdf')
            sentry.log_error(e)
            raise e


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


class PaperVoteSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'created_by',
            'created_date',
            'vote_type',
            'paper',
        ]
        model = Vote


class FigureSerializer(serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = Figure
