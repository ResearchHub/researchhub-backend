import re
import requests
import json
import utils.sentry as sentry

from django.db import transaction, IntegrityError
from django.http import QueryDict
from django.db.models import Sum

import rest_framework.serializers as serializers

from bullet_point.serializers import BulletPointTextOnlySerializer
from discussion.serializers import ThreadSerializer
from hub.models import Hub
from hub.serializers import SimpleHubSerializer, DynamicHubSerializer
from hypothesis.models import Hypothesis, Citation
from paper.lib import journal_hosts
from paper.exceptions import PaperSerializerError
from paper.models import (
    AdditionalFile,
    Flag,
    Paper,
    Vote,
    Figure,
    FeaturedPaper,
    DOI_IDENTIFIER,
    ARXIV_IDENTIFIER
)
from paper.tasks import (
    download_pdf,
    add_references,
    add_orcid_authors,
    celery_calculate_paper_twitter_score,
    celery_extract_pdf_sections
)
from paper.utils import (
    check_pdf_title,
    check_file_is_url,
    clean_abstract,
    check_url_is_pdf,
    convert_journal_url_to_pdf_url,
    convert_pdf_url_to_journal_url,
    invalidate_top_rated_cache,
    invalidate_newest_cache,
    invalidate_most_discussed_cache,
)
from researchhub.lib import get_document_id_from_path
from reputation.models import Contribution
from reputation.tasks import create_contribution
from user.models import Author, User
from user.serializers import (
    AuthorSerializer,
    UserSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer
)
from utils.arxiv import Arxiv
from utils.http import get_user_from_request, check_url_contains_pdf
from utils.siftscience import events_api, update_user_risk_score
from researchhub.settings import PAGINATION_PAGE_SIZE, TESTING
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.utils import (
    update_unified_document_to_paper,
    reset_unified_document_cache
)


class BasePaperSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()
    bullet_points = serializers.SerializerMethodField()
    csl_item = serializers.SerializerMethodField()
    discussion = serializers.SerializerMethodField()
    first_figure = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = SimpleHubSerializer(many=True, required=False)
    summary = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(read_only=True)
    user_vote = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    discussion_users = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        exclude = ['references']
        read_only_fields = [
            'score',
            'user_vote',
            'user_flag',
            'users_who_bookmarked',
            'unified_document_id',
            'slug',
            'hypothesis_id',
        ]
        model = Paper

    # def get_uploaded_by(self, obj):
    #     return UserSerializer(obj.uploaded_by, read_only=True).data

    def get_unified_document_id(self, instance):
        try:
            target_unified_doc = instance.unified_document
            return target_unified_doc.id if (
                target_unified_doc is not None
            ) else None
        except Exception:
            return None

    def to_internal_value(self, data):
        data = self._transform_to_dict(data)
        data = self._copy_data(data)

        valid_authors = []
        for author_id in data.get('authors', []):
            if isinstance(author_id, Author):
                author_id = author_id.id

            try:
                author = Author.objects.get(pk=author_id)
                valid_authors.append(author)
            except Author.DoesNotExist:
                print(f'Author with id {author_id} was not found.')
        data['authors'] = valid_authors

        valid_hubs = []
        for hub_id in data.get('hubs', []):
            if isinstance(hub_id, Hub):
                hub_id = hub_id.id

            try:
                hub = Hub.objects.filter(is_removed=False).get(pk=hub_id)
                valid_hubs.append(hub)
            except Hub.DoesNotExist:
                print(f'Hub with id {hub_id} was not found.')
        data['hubs'] = valid_hubs

        return data

    def _transform_to_dict(self, obj):
        if isinstance(obj, QueryDict):
            authors = obj.getlist('authors', [])
            hubs = obj.getlist('hubs', [])
            raw_authors = obj.getlist('raw_authors', [])
            obj = obj.dict()
            obj['authors'] = authors
            obj['hubs'] = hubs
            obj['raw_authors'] = raw_authors
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

    def get_authors(self, paper):
        serializer = AuthorSerializer(
            paper.authors.filter(claimed=True),
            many=True,
            read_only=False,
            required=False,
            context=self.context
        )
        return serializer.data

    def get_bullet_points(self, paper):
        return None

    def get_summary(self, paper):
        # return SummarySerializer(
        #     paper.summary,
        #     required=False,
        #     context=self.context
        # ).data
        return None

    def get_csl_item(self, paper):
        if self.context.get('purchase_minimal_serialization', False):
            return None

        return paper.csl_item

    def get_discussion(self, paper):
        if self.context.get('purchase_minimal_serialization', False):
            return None

        threads_queryset = paper.threads.all()
        threads = ThreadSerializer(
            threads_queryset.order_by('-created_date')[:PAGINATION_PAGE_SIZE],
            many=True,
            context=self.context
        )
        return {'count': threads_queryset.count(), 'threads': threads.data}

    def get_first_figure(self, paper):
        try:
            if len(paper.figure_list) > 0:
                figure = paper.figure_list[0]
                return FigureSerializer(figure).data
        except AttributeError:
            figure = paper.figures.filter(
                figure_type=Figure.FIGURE
            ).first()
            if figure:
                return FigureSerializer(figure).data
        return None

    def get_first_preview(self, paper):
        try:
            if len(paper.preview_list) > 0:
                figure = paper.preview_list[0]
                return FigureSerializer(figure).data
        except AttributeError:
            figure = paper.figures.filter(
                figure_type=Figure.PREVIEW
            ).first()
            if figure:
                return FigureSerializer(figure).data
        return None

    def get_user_flag(self, paper):
        if self.context.get('purchase_minimal_serialization', False):
            return None

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

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote_created_by = paper.vote_created_by
                if len(vote_created_by) == 0:
                    return None
                vote = PaperVoteSerializer(vote_created_by).data
            except AttributeError:
                try:
                    vote = paper.votes.get(created_by=user.id)
                    vote = PaperVoteSerializer(vote).data
                except Vote.DoesNotExist:
                    pass
        return vote

    def get_promoted(self, paper):
        return paper.get_promoted_score()

    def get_boost_amount(self, paper):
        return paper.get_boost_amount()

    def get_file(self, paper):
        file = paper.file
        if file:
            return paper.file.url
        return None

    def get_discussion_users(self, paper):
        contributions = Contribution.objects.filter(
            unified_document=paper.unified_document
        )
        contribution_users = contributions.values_list(
            'user',
            flat=True
        ).distinct()
        users = User.objects.filter(id__in=contribution_users)
        serializer = UserSerializer(users, many=True)
        data = serializer.data
        return data


class ContributionPaperSerializer(BasePaperSerializer):
    uploaded_by = None
    discussion = None
    first_figure = None
    first_preview = None
    bullet_points = None
    csl_item = None
    summary = None
    discussion_users = None


class PaperSerializer(BasePaperSerializer):
    raw_author_scores = serializers.SerializerMethodField()
    authors = serializers.SerializerMethodField()

    class Meta:
        exclude = ['references']
        read_only_fields = [
            'authors',
            'citations',
            'completeness',
            'csl_item',
            'discussion_count',
            'downloads',
            'edited_file_extract',
            'external_source',
            'file_created_location',
            'hot_score',
            'id',
            'is_removed',
            'is_removed_by_user',
            'oa_pdf_location',
            'pdf_file_extract',
            'pdf_license_url',
            'publication_type',
            'raw_author_scores',
            'retrieved_from_external_source',
            'score',
            'slug',
            'tagline',
            'twitter_mentions',
            'twitter_score',
            'unified_document_id',
            'uploaded_by',
            'uploaded_date',
            'user_flag',
            'users_who_bookmarked',
            'user_vote',
            'views',

        ]
        model = Paper

    def create(self, validated_data):
        request = self.context.get('request', None)
        if request:
            user = request.user
        else:
            user = None
        validated_data['uploaded_by'] = user

        # Prepare validated_data by removing m2m and file for now
        authors = validated_data.pop('authors')
        hubs = validated_data.pop('hubs')
        file = validated_data.pop('file')
        hypothesis_id = validated_data.pop('hypothesis_id', None)
        citation_type = validated_data.pop('citation_type', None)
        try:
            with transaction.atomic():
                # Temporary fix for updating read only fields
                # Not including file, pdf_url, and url because
                # those fields are processed
                for read_only_field in self.Meta.read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)

                valid_doi = self._check_valid_doi(validated_data)
                # if not valid_doi:
                #     raise IntegrityError('DETAIL: Invalid DOI')

                self._add_url(file, validated_data)
                self._clean_abstract(validated_data)
                self._add_raw_authors(validated_data)

                paper = None
                # TODO: Replace this with proper metadata handling
                if 'https://arxiv.org/abs/' in validated_data.get('url', ''):
                    arxiv_id = validated_data['url'].split('abs/')[1]
                    arxiv_id = arxiv_id.strip('.pdf')
                    arxiv_paper = Arxiv(id=arxiv_id, query=None, title=validated_data.get('title'))
                    paper = arxiv_paper.create_paper(uploaded_by=user)

                if paper is None:
                    # It is important to note that paper signals
                    # are ran after call to super
                    paper = super(PaperSerializer, self).create(validated_data)

                unified_doc = paper.unified_document
                unified_doc_id = paper.unified_document.id
                if hypothesis_id:
                    self._add_citation(
                        user,
                        hypothesis_id,
                        unified_doc,
                        citation_type
                    )

                paper_id = paper.id
                paper_title = paper.paper_title or ''
                self._check_pdf_title(paper, paper_title, file)
                # NOTE: calvinhlee - This is an antipattern. Look into changing
                Vote.objects.create(
                    paper=paper,
                    created_by=user,
                    vote_type=Vote.UPVOTE
                )

                # Now add m2m values properly
                if validated_data['paper_type'] == Paper.PRE_REGISTRATION:
                    paper.authors.add(user.author_profile)

                # TODO: Do we still need add authors from the request content?
                paper.authors.add(*authors)

                self._add_orcid_authors(paper)
                paper.hubs.add(*hubs)
                for hub in hubs:
                    hub.paper_count = hub.get_paper_count()
                    hub.save(update_fields=['paper_count'])

                try:
                    self._add_file(paper, file)
                except Exception as e:
                    sentry.log_error(
                        e,
                    )

                paper.set_paper_completeness()
                # Fix adding references
                # self._add_references(paper)

                paper.pdf_license = paper.get_license(save=False)

                update_unified_document_to_paper(paper)

                tracked_paper = events_api.track_content_paper(
                    user,
                    paper,
                    request
                )
                update_user_risk_score(user, tracked_paper)

                create_contribution.apply_async(
                    (
                        Contribution.SUBMITTER,
                        {'app_label': 'paper', 'model': 'paper'},
                        user.id,
                        unified_doc_id,
                        paper_id
                    ),
                    priority=2,
                    countdown=10
                )

                celery_calculate_paper_twitter_score.apply_async(
                    (paper_id,),
                    priority=5,
                    countdown=10
                )

                return paper
        except IntegrityError as e:
            error = PaperSerializerError(e, 'Failed to create paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )
            raise error
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to create paper')
            sentry.log_error(
                error,
                base_error=error.trigger
            )
            raise error

    def update(self, instance, validated_data):
        request = self.context.get('request', None)
        authors = validated_data.pop('authors', [None])
        hubs = validated_data.pop('hubs', [None])
        file = validated_data.pop('file', None)
        raw_authors = validated_data.pop('raw_authors', [])

        try:
            with transaction.atomic():

                # Temporary fix for updating read only fields
                # Not including file, pdf_url, and url because
                # those fields are processed
                for read_only_field in self.Meta.read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)

                self._add_url(file, validated_data)
                self._clean_abstract(validated_data)

                paper = super(PaperSerializer, self).update(
                    instance,
                    validated_data
                )
                unified_doc = paper.unified_document
                paper_title = paper.paper_title or ''
                self._check_pdf_title(paper, paper_title, file)

                if hubs:
                    current_hubs = paper.hubs.all()
                    remove_hubs = []
                    for current_hub in current_hubs:
                        if current_hub not in hubs:
                            remove_hubs.append(current_hub)
                    new_hubs = []
                    for hub in hubs:
                        if hub not in current_hubs:
                            new_hubs.append(hub)
                    paper.hubs.remove(*remove_hubs)
                    paper.hubs.add(*hubs)
                    unified_doc.hubs.remove(*remove_hubs)
                    unified_doc.hubs.add(*hubs)
                    for hub in remove_hubs:
                        hub.paper_count = hub.get_paper_count()
                        hub.save(update_fields=['paper_count'])
                    for hub in new_hubs:
                        hub.paper_count = hub.get_paper_count()
                        hub.save(update_fields=['paper_count'])

                if authors:
                    current_authors = paper.authors.all()
                    remove_authors = []
                    for author in current_authors:
                        if author not in authors:
                            remove_authors.append(author)

                    new_authors = []
                    for author in authors:
                        if author not in current_authors:
                            new_authors.append(author)
                    paper.authors.remove(*remove_authors)
                    paper.authors.add(*new_authors)

                paper.set_paper_completeness()

                if file:
                    self._add_file(paper, file)

                hub_ids = [0]
                if hubs:
                    hub_ids = list(
                        map(lambda hub: hub.id, remove_hubs + new_hubs)
                    )

                reset_unified_document_cache(hub_ids)
                invalidate_top_rated_cache(hub_ids)
                invalidate_newest_cache(hub_ids)
                invalidate_most_discussed_cache(hub_ids)

                if request:
                    tracked_paper = events_api.track_content_paper(
                        request.user,
                        paper,
                        request,
                        update=True
                    )
                    update_user_risk_score(request.user, tracked_paper)
                return paper
        except Exception as e:
            error = PaperSerializerError(e, 'Failed to update paper')
            sentry.log_error(
                e,
                base_error=error.trigger
            )
            raise error

    def _add_orcid_authors(self, paper):
        try:
            if not TESTING:
                add_orcid_authors.apply_async(
                    (paper.id,),
                    priority=5,
                    countdown=10
                )
            else:
                add_orcid_authors(paper.id)
        except Exception as e:
            sentry.log_info(e)

    def _add_references(self, paper):
        try:
            if not TESTING:
                add_references.apply_async(
                    (paper.id,),
                    priority=5,
                    countdown=30
                )
            else:
                add_references(paper.id)
        except Exception as e:
            sentry.log_info(e)

    def _add_citation(self, user, hypothesis_id, unified_document, citation_type):
        try:
            hypothesis = Hypothesis.objects.get(id=hypothesis_id)
            citation = Citation.objects.create(
                created_by=user,
                source=unified_document,
                citation_type=citation_type
            )
            citation.hypothesis.set([hypothesis])
        except Exception as e:
            sentry.log_error(e)

    def _add_file(self, paper, file):
        paper_id = paper.id
        if type(file) is not str:
            paper.file = file
            paper.save(update_fields=['file'])
            paper.extract_pdf_preview()
            celery_extract_pdf_sections.apply_async(
                (paper_id,),
                priority=3,
                countdown=15
            )
            return

        if paper.url is not None:
            if not TESTING:
                download_pdf.apply_async((paper_id,), priority=3, countdown=7)
            else:
                download_pdf(paper_id)

    def _add_url(self, file, validated_data):
        if check_file_is_url(file):
            contains_pdf = check_url_contains_pdf(file)
            is_journal_pdf = check_url_is_pdf(file)

            if contains_pdf:
                validated_data['url'] = file
                validated_data['pdf_url'] = file

            if is_journal_pdf is True:
                pdf_url = file
                journal_url, converted = convert_pdf_url_to_journal_url(file)
            elif is_journal_pdf is False:
                journal_url = file
                pdf_url, converted = convert_journal_url_to_pdf_url(file)
            else:
                validated_data['url'] = file
                return

            if converted:
                validated_data['url'] = journal_url
                validated_data['pdf_url'] = pdf_url
        return

    def _check_pdf_title(self, paper, title, file):
        if type(file) is str:
            # For now, don't do anything if file is a url
            return
        else:
            self._check_title_in_pdf(paper, title, file)

    def _check_title_in_pdf(self, paper, title, file):
        title_in_pdf = check_pdf_title(title, file)
        if not title_in_pdf:
            # e = Exception('Title not in pdf')
            # sentry.log_info(e)
            return
        else:
            paper.extract_meta_data(title=title, use_celery=True)

    def _clean_abstract(self, data):
        abstract = data.get('abstract')

        if not abstract:
            return

        cleaned_text = clean_abstract(abstract)
        data.update(abstract=cleaned_text)

    def _add_raw_authors(self, validated_data):
        raw_authors = validated_data['raw_authors']
        json_raw_authors = list(map(json.loads, raw_authors))
        validated_data['raw_authors'] = json_raw_authors

    def _check_valid_doi(self, validated_data):
        url = validated_data.get('url', '')
        pdf_url = validated_data.get('pdf_url', '')
        doi = validated_data.get('doi', '')

        for journal_host in journal_hosts:
            if url and journal_host in url:
                return True
            if pdf_url and journal_host in pdf_url:
                return True

        regex = r'(.*doi\.org\/)(.*)'

        regex_doi = re.search(regex, doi)
        if regex_doi and len(regex_doi.groups()) > 1:
            doi = regex_doi.groups()[-1]

        has_doi = doi.startswith(DOI_IDENTIFIER)
        has_arxiv = doi.startswith(ARXIV_IDENTIFIER)

        # For pdf uploads, checks if doi has an arxiv identifer
        if has_arxiv or has_doi:
            return True

        res = requests.get(
            'https://doi.org/api/handles/{}'.format(doi),
            headers=requests.utils.default_headers()
        )
        if res.status_code >= 200 and res.status_code < 400 and has_doi:
            return True
        else:
            return False

    def get_authors(self, paper):
        serializer = AuthorSerializer(
            paper.authors.all(),
            many=True,
            read_only=False,
            required=False,
            context=self.context
        )
        return serializer.data

    def get_discussion(self, paper):
        return None

    def get_file(self, paper):
        external_source = paper.external_source
        file = paper.file
        if external_source and external_source.lower() == 'arxiv':
            pdf_url = paper.pdf_url
            url = paper.url
            if pdf_url:
                return pdf_url
            elif url:
                return url
            return None
        elif file:
            return file.url
        return None

    def get_raw_author_scores(self, paper):
        get_scores = self.context.get('get_raw_author_scores', False)
        scores = []
        if get_scores:
            raw_authors = paper.raw_authors
            if raw_authors:
                for author in raw_authors:
                    if isinstance(author, str):
                        author = json.loads(author)

                    if not isinstance(author, dict):
                        scores.append(0)
                        continue

                    score = Paper.objects.filter(
                        raw_authors__contains=[
                            {
                                'first_name': author.get('first_name'),
                                'last_name': author.get('last_name')
                            }
                        ]
                    ).aggregate(
                        Sum('score')
                    )['score__sum']
                    scores.append(score)
        return scores


class HubPaperSerializer(BasePaperSerializer):
    def get_bullet_points(self, paper):
        # bullet_points = paper.bullet_points.filter(
        #     ordinal__isnull=False
        # ).order_by('ordinal')[:3]
        return BulletPointTextOnlySerializer(
            paper.bullet_points,
            many=True,
            context=self.context,
        ).data

    # def get_uploaded_by(self, paper):
    #     serializer_context = {'request': self.context.get('request'), 'no_balance': True}
    #     data = UserSerializer(paper.uploaded_by, context=serializer_context, read_only=True).data
    #     return data

    def get_csl_item(self, paper):
        return None

    def get_discussion(self, paper):
        return None

    def get_referenced_by(self, paper):
        return None

    def get_references(self, paper):
        return None


class FeaturedPaperSerializer(serializers.ModelSerializer):
    paper = PaperSerializer()

    class Meta:
        fields = '__all__'
        model = FeaturedPaper


class PaperReferenceSerializer(serializers.ModelSerializer):
    hubs = SimpleHubSerializer(
        many=True,
        required=False,
        context={'no_subscriber_info': True}
    )
    first_figure = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        fields = [
            'id',
            'title',
            'hubs',
            'first_figure',
            'first_preview',
        ]
        model = Paper

    def get_first_figure(self, paper):
        return None

    def get_first_preview(self, paper):
        try:
            if len(paper.preview_list) > 0:
                figure = paper.preview_list[0]
                return FigureSerializer(figure).data
        except AttributeError:
            figure = paper.figures.filter(
                figure_type=Figure.PREVIEW
            ).first()
            if figure:
                return FigureSerializer(figure).data
        return None


class DynamicPaperSerializer(DynamicModelFieldSerializer):
    authors = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    discussion_users = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        model = Paper
        fields = '__all__'

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        context = self.context
        _context_fields = context.get('pap_dps_get_user_vote', {})        
        if user:
            try:
                vote_created_by = paper.vote_created_by
                if len(vote_created_by) == 0:
                    return None
                vote = DynamicPaperVoteSerializer(
                    vote_created_by,
                    context=self.context,
                    **_context_fields,
                ).data
            except AttributeError:
                try:
                    vote = paper.votes.get(created_by=user.id)
                    vote = DynamicPaperVoteSerializer(
                        vote,
                        context=self.context,
                        **_context_fields,
                    ).data
                except Vote.DoesNotExist:
                    pass
        return vote

    def get_authors(self, paper):
        context = self.context
        _context_fields = context.get('pap_dps_get_authors', {})

        serializer = DynamicAuthorSerializer(
            paper.authors.all(),
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_boost_amount(self, paper):
        return paper.get_boost_amount()

    def get_discussion_users(self, paper):
        context = self.context
        _context_fields = context.get('pap_dps_get_discussion_users', {})

        contributions = Contribution.objects.filter(
            unified_document=paper.unified_document
        )
        contribution_users = contributions.values_list(
            'user',
            flat=True
        ).distinct()
        users = User.objects.filter(id__in=contribution_users)

        serializer = DynamicUserSerializer(
            users,
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_hubs(self, paper):
        context = self.context
        _context_fields = context.get('pap_dps_get_hubs', {})
        serializer = DynamicHubSerializer(
            paper.hubs,
            many=True,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_first_preview(self, paper):
        context = self.context
        _context_fields = context.get('pap_dps_get_first_preview', {})
        try:
            if paper.preview_list.exists():
                figure = paper.preview_list.first()
                serializer = DynamicFigureSerializer(
                    figure,
                    context=context,
                    **_context_fields
                )
                return serializer.data
        except Exception:
            figure = paper.figures.filter(
                figure_type=Figure.PREVIEW
            ).first()
            if figure:
                serializer = DynamicFigureSerializer(
                    figure,
                    context=context,
                    **_context_fields
                )
                return serializer.data
        return None

    def get_unified_document(self, paper):
        from researchhub_document.serializers import (
          DynamicUnifiedDocumentSerializer
        )
        context = self.context
        _context_fields = context.get('pap_dps_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            paper.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_uploaded_by(self, paper):
        context = self.context
        _context_fields = context.get('pap_dps_get_uploaded_by', {})
        uploaded_by = paper.uploaded_by

        if not uploaded_by:
            return None

        serializer = DynamicUserSerializer(
            uploaded_by,
            context=context,
            **_context_fields
        )
        return serializer.data


class AdditionalFileSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            'id',
            'file',
            'paper',
            'created_by',
            'created_date',
            'updated_date'
        ]
        read_only_fields = [
            'id',
            'paper',
            'created_by',
            'created_date',
            'updated_date',
        ]
        model = AdditionalFile

    def create(self, validated_data):
        request = self.context['request']
        user = request.user
        paper_id = get_document_id_from_path(request)
        validated_data['created_by'] = user
        validated_data['paper'] = Paper.objects.get(pk=paper_id)
        additional_file = super().create(validated_data)
        return additional_file


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
            'id',
            'created_by',
            'created_date',
            'vote_type',
            'paper',
        ]
        model = Vote

class DynamicPaperVoteSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = '__all__'
        model = Vote


class FigureSerializer(serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = Figure

    def create(self, validated_data):
        request = self.context['request']
        user = request.user
        if user.is_anonymous:
            user = None
        validated_data['created_by'] = user
        figure = super().create(validated_data)
        return figure


class DynamicFigureSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = '__all__'
        model = Figure
