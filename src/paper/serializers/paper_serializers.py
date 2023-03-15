import json
import re

import requests
import rest_framework.serializers as serializers
from django.contrib.admin.options import get_content_type_for_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import QueryDict

import utils.sentry as sentry
from discussion.models import Flag as GrmFlag
from discussion.models import Vote as GrmVote
from discussion.reaction_serializers import GenericReactionSerializerMixin
from discussion.serializers import DynamicFlagSerializer
from discussion.serializers import DynamicVoteSerializer as DynamicGrmVoteSerializer
from discussion.serializers import ThreadSerializer
from hub.models import Hub
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from hypothesis.models import Citation, Hypothesis
from paper.exceptions import PaperSerializerError
from paper.lib import journal_hosts
from paper.models import (
    ARXIV_IDENTIFIER,
    DOI_IDENTIFIER,
    AdditionalFile,
    Figure,
    Paper,
    PaperSubmission,
)
from paper.tasks import (  # celery_calculate_paper_twitter_score,
    add_orcid_authors,
    celery_extract_pdf_sections,
    download_pdf,
)
from paper.utils import (
    check_file_is_url,
    check_pdf_title,
    check_url_is_pdf,
    clean_abstract,
    convert_journal_url_to_pdf_url,
    convert_pdf_url_to_journal_url,
)
from reputation.models import Bounty, Contribution
from reputation.tasks import create_contribution
from researchhub.lib import get_document_id_from_path
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub.settings import PAGINATION_PAGE_SIZE, TESTING
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    HOT,
    NEW,
    UPVOTED,
)
from researchhub_document.utils import (
    reset_unified_document_cache,
    update_unified_document_to_paper,
)
from user.models import Author
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils.http import check_url_contains_pdf, get_user_from_request
from utils.siftscience import events_api, update_user_risk_score


class BasePaperSerializer(serializers.ModelSerializer, GenericReactionSerializerMixin):
    authors = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    bullet_points = serializers.SerializerMethodField()
    csl_item = serializers.SerializerMethodField()
    discussion = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    first_figure = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = SimpleHubSerializer(many=True, required=False)
    promoted = serializers.SerializerMethodField()
    score = serializers.ReadOnlyField()  # GRM
    summary = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(read_only=True)
    user_flag = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        exclude = ["references"]
        read_only_fields = [
            "user_vote",
            "user_flag",
            "users_who_bookmarked",
            "unified_document_id",
            "slug",
            "hypothesis_id",
        ]
        model = Paper

    def get_unified_document_id(self, instance):
        try:
            target_unified_doc = instance.unified_document
            return target_unified_doc.id if (target_unified_doc is not None) else None
        except Exception:
            return None

    # overriding innate django function
    def to_internal_value(self, data):
        data = self._transform_to_dict(data)
        data = self._copy_data(data)

        valid_authors = []
        for author_id in data.get("authors", []):
            if isinstance(author_id, Author):
                author_id = author_id.id
            if isinstance(author_id, dict):
                author_id = author_id.get("id", None)
            try:
                author = Author.objects.get(pk=author_id)
                valid_authors.append(author)
            except Author.DoesNotExist:
                print(f"Author with id {author_id} was not found.")
        data["authors"] = valid_authors

        valid_hubs = []
        for hub_id in data.get("hubs", []):
            if isinstance(hub_id, Hub):
                hub_id = hub_id.id

            try:
                hub = Hub.objects.filter(is_removed=False).get(pk=hub_id)
                valid_hubs.append(hub)
            except Hub.DoesNotExist:
                print(f"Hub with id {hub_id} was not found.")
        data["hubs"] = valid_hubs

        return data

    def _transform_to_dict(self, obj):
        if isinstance(obj, QueryDict):
            authors = obj.getlist("authors", [])
            hubs = obj.getlist("hubs", [])
            raw_authors = obj.getlist("raw_authors", [])
            obj = obj.dict()
            obj["authors"] = authors
            obj["hubs"] = hubs
            obj["raw_authors"] = raw_authors
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
            file = data.pop("file")
        except KeyError:
            pass

        data = data.copy()
        data["file"] = file
        return data

    def get_authors(self, paper):
        serializer = AuthorSerializer(
            paper.authors.filter(claimed=True),
            many=True,
            read_only=False,
            required=False,
            context=self.context,
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
        if self.context.get("purchase_minimal_serialization", False):
            return None

        return paper.csl_item

    def get_discussion(self, paper):
        if self.context.get("purchase_minimal_serialization", False):
            return None

        threads_queryset = paper.threads.all()
        threads = ThreadSerializer(
            threads_queryset.order_by("-created_date")[:PAGINATION_PAGE_SIZE],
            many=True,
            context=self.context,
        )
        return {"count": threads_queryset.count(), "threads": threads.data}

    def get_first_figure(self, paper):
        try:
            if len(paper.figure_list) > 0:
                figure = paper.figure_list[0]
                return FigureSerializer(figure).data
        except AttributeError:
            figure = paper.figures.filter(figure_type=Figure.FIGURE).first()
            if figure:
                return FigureSerializer(figure).data
        return None

    def get_first_preview(self, paper):
        try:
            figure = paper.figures.filter(figure_type=Figure.PREVIEW).first()
            if figure:
                return FigureSerializer(figure).data
        except AttributeError:
            return None

    def get_user_flag(self, paper):
        if self.context.get("purchase_minimal_serialization", False):
            return None

        flag = None
        user = get_user_from_request(self.context)
        if user:
            try:
                flag = paper.flags.get(created_by=user.id)
                flag = DynamicFlagSerializer(flag).data
            except GrmFlag.DoesNotExist:
                pass
        return flag

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = paper.votes.get(created_by=user.id)
                vote = DynamicGrmVoteSerializer(vote).data
            except GrmVote.DoesNotExist:
                pass
        return vote

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document,
            _include_fields=[
                "id",
                "reviews",
                "title",
                "documents",
                "paper_title",
                "slug",
                "is_removed",
                "document_type",
                "created_by",
            ],
            context={
                "doc_duds_get_created_by": {
                    "_include_fields": [
                        "id",
                        "author_profile",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
                "doc_duds_get_documents": {
                    "_include_fields": [
                        "id",
                        "title",
                        "slug",
                        "paper_title",
                    ]
                },
            },
            many=False,
        )

        return serializer.data

    def get_promoted(self, paper):
        return paper.get_promoted_score()

    def get_boost_amount(self, paper):
        return paper.get_boost_amount()

    def get_file(self, paper):
        file = paper.file
        if file:
            return paper.file.url
        return None


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
    authors = serializers.SerializerMethodField()
    uploaded_date = serializers.ReadOnlyField()  # GRM

    class Meta:
        exclude = ["references"]
        read_only_fields = [
            "authors",
            "citations",
            "completeness",
            "csl_item",
            "discussion_count",
            "downloads",
            "edited_file_extract",
            "external_source",
            "file_created_location",
            "id",
            "is_open_access",
            "is_removed_by_user",
            "is_removed",
            "oa_pdf_location",
            "pdf_file_extract",
            "pdf_license_url",
            "publication_type",
            "retrieved_from_external_source",
            "score",
            "slug",
            "tagline",
            "twitter_mentions",
            "twitter_score",
            "unified_document_id",
            "unified_document",
            "user_flag",
            "user_vote",
            "users_who_bookmarked",
            "views",
        ]

        patch_read_only_fields = ["uploaded_by"]
        model = Paper

    def create(self, validated_data):
        request = self.context.get("request", None)
        if request:
            user = request.user
        else:
            user = None
        validated_data["uploaded_by"] = user

        # if "url" in validated_data or "pdf_url" in validated_data:
        #     error = Exception("URL uploading is deprecated")
        #     sentry.log_error(error)
        #     raise error

        # Prepare validated_data by removing m2m
        authors = validated_data.pop("authors")
        hubs = validated_data.pop("hubs")
        hypothesis_id = validated_data.pop("hypothesis_id", None)
        citation_type = validated_data.pop("citation_type", None)
        file = validated_data.get("file")
        try:
            with transaction.atomic():
                # Temporary fix for updating read only fields
                # Not including file, pdf_url, and url because
                # those fields are processed
                for read_only_field in self.Meta.read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)

                # valid_doi = self._check_valid_doi(validated_data)
                # if not valid_doi:
                #     raise IntegrityError('DETAIL: Invalid DOI')

                self._add_url(file, validated_data)
                [
                    _,
                    abstract_src_encoded_file,
                    abstract_src_type,
                ] = self._clean_abstract_or_abstract_src(validated_data)
                self._add_raw_authors(validated_data)

                paper = None

                if paper is None:
                    # It is important to note that paper signals
                    # are ran after call to super
                    paper = super(PaperSerializer, self).create(validated_data)
                    paper.full_clean(exclude=["paper_type"])

                # TODO: calvinhlee look into auto-pull and abstract abstractions
                # paper.abstract
                # if (abstract_src_encoded_file and abstract_src_type):
                #     paper.abstract_src.save(
                #         f'RH-PAPER-ABSTRACT-SRC-USER-{request.user.id}.txt',
                #         abstract_src_encoded_file
                #     )

                unified_doc = paper.unified_document
                unified_doc_id = paper.unified_document.id
                if hypothesis_id:
                    self._add_citation(user, hypothesis_id, unified_doc, citation_type)

                paper_id = paper.id
                # NOTE: calvinhlee - This is an antipattern. Look into changing
                GrmVote.objects.create(
                    content_type=get_content_type_for_model(paper),
                    created_by=user,
                    object_id=paper.id,
                    vote_type=GrmVote.UPVOTE,
                )

                # Now add m2m values properly
                if validated_data["paper_type"] == Paper.PRE_REGISTRATION:
                    paper.authors.add(user.author_profile)

                # TODO: Do we still need add authors from the request content?
                paper.authors.add(*authors)

                self._add_orcid_authors(paper)
                paper.hubs.add(*hubs)
                for hub in hubs:
                    hub.paper_count = hub.get_paper_count()
                    hub.save(update_fields=["paper_count"])

                try:
                    file = paper.file
                    self._add_file(paper, file)
                except Exception as e:
                    sentry.log_error(
                        e,
                    )

                paper.set_paper_completeness()

                paper.pdf_license = paper.get_license(save=False)

                update_unified_document_to_paper(paper)

                tracked_paper = events_api.track_content_paper(user, paper, request)
                update_user_risk_score(user, tracked_paper)

                create_contribution.apply_async(
                    (
                        Contribution.SUBMITTER,
                        {"app_label": "paper", "model": "paper"},
                        user.id,
                        unified_doc_id,
                        paper_id,
                    ),
                    priority=3,
                    countdown=10,
                )

                # celery_calculate_paper_twitter_score.apply_async(
                #     (paper_id,), priority=5, countdown=10
                # )

                hub_ids = unified_doc.hubs.values_list("id", flat=True)
                if hub_ids.exists():
                    reset_unified_document_cache(
                        hub_ids,
                        document_type=["paper", "all"],
                        filters=[NEW],
                        with_default_hub=True,
                    )
                paper.save()
                return paper
        except IntegrityError as e:
            sentry.log_error(e)
            raise e
        except Exception as e:
            error = PaperSerializerError(e, "Failed to create paper")
            sentry.log_error(error, base_error=error.trigger)
            raise error

    def update(self, instance, validated_data):
        authors = validated_data.pop("authors", [None])
        file = validated_data.pop("file", None)
        hubs = validated_data.pop("hubs", [None])
        raw_authors = validated_data.pop("raw_authors", [])
        request = self.context.get("request", None)

        try:
            with transaction.atomic():

                # Temporary fix for updating read only fields
                # Not including file, pdf_url, and url because
                # those fields are processed
                read_only_fields = (
                    self.Meta.read_only_fields + self.Meta.patch_read_only_fields
                )
                for read_only_field in read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)
                self._add_url(file, validated_data)
                [
                    _,
                    abstract_src_encoded_file,
                    abstract_src_type,
                ] = self._clean_abstract_or_abstract_src(validated_data)

                paper = super(PaperSerializer, self).update(instance, validated_data)
                if abstract_src_encoded_file and abstract_src_type:
                    paper.abstract_src.save(
                        f"RH-PAPER-ABSTRACT-SRC-USER-{request.user.id}.txt",
                        abstract_src_encoded_file,
                    )
                paper.full_clean(exclude=["paper_type"])

                unified_doc = paper.unified_document
                new_hubs = []
                remove_hubs = []
                if hubs:
                    current_hubs = paper.hubs.all()
                    for current_hub in current_hubs:
                        if current_hub not in hubs:
                            remove_hubs.append(current_hub)
                    for hub in hubs:
                        if hub not in current_hubs:
                            new_hubs.append(hub)
                    paper.hubs.remove(*remove_hubs)
                    paper.hubs.add(*hubs)
                    unified_doc.hubs.remove(*remove_hubs)
                    unified_doc.hubs.add(*hubs)
                    for hub in remove_hubs:
                        hub.paper_count = hub.get_paper_count()
                        hub.save(update_fields=["paper_count"])
                    for hub in new_hubs:
                        hub.paper_count = hub.get_paper_count()
                        hub.save(update_fields=["paper_count"])

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

                updated_hub_ids = list(map(lambda hub: hub.id, remove_hubs + new_hubs))
                if len(updated_hub_ids) > 0:
                    reset_unified_document_cache(
                        hub_ids=updated_hub_ids,
                        document_type=["paper", "all"],
                        filters=[NEW, UPVOTED, HOT, DISCUSSED],
                        with_default_hub=True,
                    )

                if request:
                    tracked_paper = events_api.track_content_paper(
                        request.user, paper, request, update=True
                    )
                    update_user_risk_score(request.user, tracked_paper)
                return paper
        except Exception as e:
            error = PaperSerializerError(e, "Failed to update paper")
            sentry.log_error(e, base_error=error.trigger)
            raise error

    def _add_orcid_authors(self, paper):
        try:
            if not TESTING:
                add_orcid_authors.apply_async((paper.id,), priority=5, countdown=10)
            else:
                add_orcid_authors(paper.id)
        except Exception as e:
            sentry.log_info(e)

    def _add_citation(self, user, hypothesis_id, unified_document, citation_type):
        try:
            hypothesis = Hypothesis.objects.get(id=hypothesis_id)
            citation = Citation.objects.create(
                created_by=user, source=unified_document, citation_type=citation_type
            )
            citation.hypothesis.set([hypothesis])
        except Exception as e:
            sentry.log_error(e)

    def _add_file(self, paper, file):
        paper_id = paper.id
        if type(file) is not str:
            paper.file = file
            paper.save(update_fields=["file"])
            paper.extract_pdf_preview()
            celery_extract_pdf_sections.apply_async(
                (paper_id,), priority=3, countdown=15
            )
            return

        if paper.url is not None:
            if not TESTING:
                download_pdf.apply_async((paper_id,), priority=3, countdown=7)
            else:
                download_pdf(paper_id)

    def _add_url(self, file, validated_data):
        if check_file_is_url(file):
            validated_data["file"] = None
            contains_pdf = check_url_contains_pdf(file)
            is_journal_pdf = check_url_is_pdf(file)

            if contains_pdf:
                validated_data["url"] = file
                validated_data["pdf_url"] = file

            if is_journal_pdf is True:
                pdf_url = file
                journal_url, converted = convert_pdf_url_to_journal_url(file)
            elif is_journal_pdf is False:
                journal_url = file
                pdf_url, converted = convert_journal_url_to_pdf_url(file)
            else:
                validated_data["url"] = file
                return

            if converted:
                validated_data["url"] = journal_url
                validated_data["pdf_url"] = pdf_url
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

    def _clean_abstract_or_abstract_src(self, data):
        abstract = data.get("abstract")
        if abstract:
            cleaned_text = clean_abstract(abstract)
            data.update(abstract=cleaned_text)

        abstract_src = data.get("abstract_src")
        abstract_src_type = data.get("abstract_src_type")
        abstract_src_encoded_file = None
        if abstract_src is not None:
            abstract_src_encoded_file = ContentFile(data["abstract_src"].encode())
        if abstract_src and abstract_src_type:
            data.update(abstract_src=abstract_src_encoded_file)

        return [abstract, abstract_src_encoded_file, abstract_src_type]

    def _add_raw_authors(self, validated_data):
        raw_authors = validated_data["raw_authors"]
        json_raw_authors = list(map(json.loads, raw_authors))
        validated_data["raw_authors"] = json_raw_authors

    def _check_valid_doi(self, validated_data):
        url = validated_data.get("url", "")
        pdf_url = validated_data.get("pdf_url", "")
        doi = validated_data.get("doi", "")

        for journal_host in journal_hosts:
            if url and journal_host in url:
                return True
            if pdf_url and journal_host in pdf_url:
                return True

        regex = r"(.*doi\.org\/)(.*)"

        regex_doi = re.search(regex, doi)
        if regex_doi and len(regex_doi.groups()) > 1:
            doi = regex_doi.groups()[-1]

        has_doi = doi.startswith(DOI_IDENTIFIER)
        has_arxiv = doi.startswith(ARXIV_IDENTIFIER)

        # For pdf uploads, checks if doi has an arxiv identifer
        if has_arxiv or has_doi:
            return True

        res = requests.get(
            "https://doi.org/api/handles/{}".format(doi),
            headers=requests.utils.default_headers(),
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
            context=self.context,
        )
        return serializer.data

    def get_discussion(self, paper):
        return None

    def get_file(self, paper):
        external_source = paper.external_source
        file = paper.file
        if external_source and external_source.lower() == "arxiv":
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


class PaperReferenceSerializer(
    serializers.ModelSerializer, GenericReactionSerializerMixin
):
    hubs = SimpleHubSerializer(
        many=True, required=False, context={"no_subscriber_info": True}
    )
    first_figure = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        fields = [
            "id",
            "title",
            "hubs",
            "first_figure",
            "first_preview",
        ]
        model = Paper

    def get_first_figure(self, paper):
        return None

    def get_first_preview(self, paper):
        try:
            figure = paper.figures.filter(figure_type=Figure.PREVIEW).first()
            if figure:
                return FigureSerializer(figure).data
        except AttributeError:
            return None


class DynamicPaperSerializer(
    DynamicModelFieldSerializer, GenericReactionSerializerMixin
):
    authors = serializers.SerializerMethodField()
    abstract_src_markdown = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    bounties = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    class Meta:
        model = Paper
        fields = "__all__"

    def get_abstract_src_markdown(self, paper):
        try:
            return paper.abstract_src.read().decode("utf-8")
        except Exception as _e:
            # abstract src file may not be present which is ok
            return None

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        context = self.context
        _context_fields = context.get("pap_dps_get_user_vote", {})
        if user:
            try:
                vote = paper.votes.get(created_by=user.id)
                vote = DynamicGrmVoteSerializer(
                    vote,
                    context=self.context,
                    **_context_fields,
                ).data

            except GrmVote.DoesNotExist:
                pass

        return vote

    def get_authors(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_authors", {})

        serializer = DynamicAuthorSerializer(
            paper.authors.all(), many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_boost_amount(self, paper):
        if paper.purchases.exists():
            return paper.get_boost_amount()
        return 0

    def get_bounties(self, paper):
        # TODO: Remove temporary return
        return None
        from reputation.serializers import DynamicBountySerializer

        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile", "id")},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "profile_image",
                    "first_name",
                    "last_name",
                )
            },
        }
        thread_ids = paper.threads.values_list("id", flat=True)
        bounties = Bounty.objects.filter(
            item_content_type__model="researchhubunifieddocument",
            item_object_id__in=thread_ids,
        )
        serializer = DynamicBountySerializer(
            bounties,
            many=True,
            context=context,
            _include_fields=("amount", "created_by", "expiration_date", "id", "status"),
        )
        return serializer.data

    def get_hubs(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_hubs", {})
        serializer = DynamicHubSerializer(
            paper.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_first_preview(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_first_preview", {})
        if paper.figures.exists():
            figure = paper.figures.filter(figure_type=Figure.PREVIEW).first()
            if figure:
                serializer = DynamicFigureSerializer(
                    figure, context=context, **_context_fields
                )
                return serializer.data
        return None

    def get_score(self, paper):
        return paper.calculate_score()

    def get_unified_document(self, paper):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        # NOTE: calvinhlee - dynamic handling is very confusing. This has to be better.
        context = self.context
        _context_fields = context.get(
            "pap_dps_get_unified_document", {"_exclude_fields": ["documents"]}
        )

        serializer = DynamicUnifiedDocumentSerializer(
            paper.unified_document,
            context=context,
            **_context_fields,
        )

        return serializer.data

    def get_uploaded_by(self, paper):
        context = self.context
        _context_fields = context.get("pap_dps_get_uploaded_by", {})
        uploaded_by = paper.uploaded_by

        if not uploaded_by:
            return None

        serializer = DynamicUserSerializer(
            uploaded_by, context=context, **_context_fields
        )
        return serializer.data


class AdditionalFileSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "file", "paper", "created_by", "created_date", "updated_date"]
        read_only_fields = [
            "id",
            "paper",
            "created_by",
            "created_date",
            "updated_date",
        ]
        model = AdditionalFile

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        paper_id = get_document_id_from_path(request)
        validated_data["created_by"] = user
        validated_data["paper"] = Paper.objects.get(pk=paper_id)
        additional_file = super().create(validated_data)
        return additional_file


class BookmarkSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    bookmarks = PaperSerializer(many=True)


class FigureSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        model = Figure

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        if user.is_anonymous:
            user = None
        validated_data["created_by"] = user
        figure = super().create(validated_data)
        return figure


class DynamicFigureSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = "__all__"
        model = Figure


class PaperSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        model = PaperSubmission
        read_only_fields = [
            "id",
            "created_date",
            "paper_status",
            "updated_date",
        ]


class DynamicPaperSubmissionSerializer(DynamicModelFieldSerializer):
    paper = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = PaperSubmission

    def get_paper(self, paper_submission):
        context = self.context
        _context_fields = context.get("pap_dpss_get_paper", {})
        serializer = DynamicPaperSerializer(
            paper_submission.paper, context=context, **_context_fields
        )
        return serializer.data

    def get_uploaded_by(self, paper_submission):
        context = self.context
        _context_fields = context.get("pap_dpss_get_uploaded_by", {})

        serializer = DynamicUserSerializer(
            paper_submission.uploaded_by, context=context, **_context_fields
        )
        return serializer.data
