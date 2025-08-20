import json
import re

import requests
import rest_framework.serializers as serializers
from django.contrib.admin.options import get_content_type_for_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import QueryDict

import utils.sentry as sentry
from discussion.models import Flag, Vote
from discussion.serializers import (
    DynamicFlagSerializer,
    DynamicVoteSerializer,
    GenericReactionSerializerMixin,
)
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from paper.exceptions import PaperSerializerError
from paper.lib import journal_hosts
from paper.models import (
    ARXIV_IDENTIFIER,
    DOI_IDENTIFIER,
    Figure,
    Paper,
    PaperSubmission,
    PaperVersion,
)
from paper.related_models.authorship_model import Authorship
from paper.tasks import celery_extract_pdf_sections, download_pdf
from paper.utils import (
    check_file_is_url,
    check_pdf_title,
    check_url_is_pdf,
    clean_abstract,
    convert_journal_url_to_pdf_url,
    convert_pdf_url_to_journal_url,
    pdf_copyright_allows_display,
)
from purchase.models import Purchase
from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub.settings import TESTING
from researchhub_document.utils import update_unified_document_to_paper
from review.serializers.peer_review_serializer import PeerReviewSerializer
from user.models import Author
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils.http import check_url_contains_pdf, get_user_from_request


class BasePaperSerializer(serializers.ModelSerializer, GenericReactionSerializerMixin):
    authors = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    bullet_points = serializers.SerializerMethodField()
    csl_item = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    pdf_copyright_allows_display = serializers.SerializerMethodField()
    first_figure = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    score = serializers.ReadOnlyField()
    unified_document = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    uploaded_by = UserSerializer(read_only=True)
    user_flag = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    version_list = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        exclude = ["references"]
        read_only_fields = [
            "user_vote",
            "user_flag",
            "unified_document_id",
            "slug",
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

        return data

    def _transform_to_dict(self, obj):
        if isinstance(obj, QueryDict):
            authors = obj.getlist("authors", [])
            raw_authors = obj.getlist("raw_authors", [])
            obj = obj.dict()
            obj["authors"] = authors
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

    def get_csl_item(self, paper):
        if self.context.get("purchase_minimal_serialization", False):
            return None

        return paper.csl_item

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
        # If we don't show the PDFs on the paper page, we shouldn't have previews either
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )
        if (
            not self.get_pdf_copyright_allows_display(paper)
            and exclude_copyrighted_content
        ):
            return None

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
            except Flag.DoesNotExist:
                pass
        return flag

    def get_user_vote(self, paper):
        vote = None
        user = get_user_from_request(self.context)
        if user:
            try:
                vote = paper.votes.get(created_by=user.id)
                vote = DynamicVoteSerializer(vote).data
            except Vote.DoesNotExist:
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

    def get_pdf_copyright_allows_display(self, paper):
        return pdf_copyright_allows_display(paper)

    def get_file(self, paper):
        file = paper.file
        if not file:
            return None

        # Don't return copyrighted content by default, but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.file.url
        return None

    def get_pdf_url(self, paper):
        if not paper.pdf_url:
            return None

        # Don't return copyrighted content by default, but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.pdf_url
        return None

    def get_version(self, paper):
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
            return paper_version.version
        except PaperVersion.DoesNotExist:
            return 1

    def get_version_list(self, paper) -> list:
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
        except PaperVersion.DoesNotExist:
            return [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                }
            ]

        paper_versions = (
            PaperVersion.objects.filter(
                original_paper_id=paper_version.original_paper_id
            )
            .select_related("paper")
            .order_by("version")
        )
        latest_version = paper_versions.last()

        # Return a list of version pointing to the paper_id
        return [
            {
                "version": version.version,
                "paper_id": version.paper.id,
                "publication_status": version.publication_status,
                "published_date": (
                    version.paper.paper_publish_date.strftime("%Y-%m-%d")
                    if version.paper.paper_publish_date
                    else None
                ),
                "message": version.message,
                "is_latest": version.version == latest_version.version,
                "is_version_of_record": (
                    version.version == latest_version.version
                    and version.publication_status == PaperVersion.PUBLISHED
                ),
            }
            for version in paper_versions
        ]

    def get_hubs(self, paper):
        if paper.unified_document:
            return SimpleHubSerializer(
                paper.unified_document.hubs.all(), many=True
            ).data
        return []


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
    uploaded_date = serializers.ReadOnlyField()

    class Meta:
        exclude = ["references"]
        read_only_fields = [
            "authors",
            "citations",
            "completeness",
            "csl_item",
            "discussion_count",
            "external_source",
            "file_created_location",
            "id",
            "is_open_access",
            "is_removed",
            "oa_pdf_location",
            "pdf_license_url",
            "retrieved_from_external_source",
            "score",
            "slug",
            "tagline",
            "unified_document_id",
            "unified_document",
            "user_flag",
            "user_vote",
            "version",
            "version_list",
        ]
        moderator_only_update_fields = [
            "pdf_license",
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

        # Prepare validated_data by removing m2m
        authors = validated_data.pop("authors")
        hubs = validated_data.pop("hubs", [])
        file = validated_data.get("file")
        try:
            with transaction.atomic():
                # Temporary fix for updating read only fields
                # Not including file, pdf_url, and url because
                # those fields are processed
                for read_only_field in self.Meta.read_only_fields:
                    if read_only_field in validated_data:
                        validated_data.pop(read_only_field, None)

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

                unified_doc_id = paper.unified_document.id
                paper_id = paper.id
                # NOTE: calvinhlee - This is an antipattern. Look into changing
                Vote.objects.create(
                    content_type=get_content_type_for_model(paper),
                    created_by=user,
                    object_id=paper.id,
                    vote_type=Vote.UPVOTE,
                )

                # Now add m2m values properly
                if validated_data["paper_type"] == Paper.PRE_REGISTRATION:
                    paper.authors.add(user.author_profile)

                # TODO: Do we still need add authors from the request content?
                paper.authors.add(*authors)
                paper.unified_document.hubs.add(*hubs)

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
        request = self.context.get("request", None)

        # Check permissions
        if not request.user.moderator:
            for field in self.Meta.moderator_only_update_fields:
                if field in validated_data:
                    validated_data.pop(field, None)

        validated_data.pop("authors", [None])
        file = validated_data.pop("file", None)
        hubs = validated_data.pop("hubs", None)
        pdf_license = validated_data.get("pdf_license", None)
        validated_data.pop("raw_authors", [])

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
                if hubs is not None:
                    # Create list of hub IDs independent of whether hubs is
                    # a list of Hub objects or a list of hub IDs.
                    new_hub_ids = [h.id if hasattr(h, "id") else int(h) for h in hubs]

                    # Get the current hub IDs from the unified document
                    current_hub_ids = list(
                        unified_doc.hubs.values_list("id", flat=True)
                    )

                    # Calculate the actual delta
                    remove_ids = [
                        hid for hid in current_hub_ids if hid not in new_hub_ids
                    ]
                    add_ids = [hid for hid in new_hub_ids if hid not in current_hub_ids]

                    if remove_ids:
                        unified_doc.hubs.remove(*remove_ids)
                    if add_ids:
                        unified_doc.hubs.add(*add_ids)

                if pdf_license:
                    paper.pdf_license = pdf_license
                    paper.save(update_fields=["pdf_license"])

                paper.set_paper_completeness()

                if file:
                    self._add_file(paper, file)

                return paper
        except Exception as e:
            error = PaperSerializerError(e, "Failed to update paper")
            sentry.log_error(e, base_error=error.trigger)
            raise error

    def _add_file(self, paper, file):
        paper_id = paper.id
        if type(file) is not str:
            paper.file = file
            paper.save(update_fields=["file"])
            paper.compress_and_linearize_file()
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


class AuthorshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Authorship
        fields = "__all__"


class DynamicAuthorshipSerializer(DynamicModelFieldSerializer):
    class Meta:
        fields = "__all__"
        model = Authorship

    def to_representation(self, authorship):
        context = self.context
        context_fields = {
            "_include_fields": [
                "id",
                "first_name",
                "last_name",
                "user",
            ]
        }
        author_data = DynamicAuthorSerializer(
            authorship.author,
            context=context,
            **context_fields,
        ).data

        authorship_data = {
            "position": authorship.author_position,
            "is_corresponding": authorship.is_corresponding,
        }

        # Nest authorship details within author data
        return {**author_data, "authorship": authorship_data}


class DynamicPaperSerializer(
    DynamicModelFieldSerializer, GenericReactionSerializerMixin
):
    authors = serializers.SerializerMethodField()
    abstract_src_markdown = serializers.SerializerMethodField()
    boost_amount = serializers.SerializerMethodField()
    bounties = serializers.SerializerMethodField()
    discussions = serializers.SerializerMethodField()
    discussion_aggregates = serializers.SerializerMethodField()
    first_preview = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    pdf_copyright_allows_display = serializers.SerializerMethodField()
    peer_reviews = PeerReviewSerializer(many=True, read_only=True)
    version = serializers.SerializerMethodField()
    version_list = serializers.SerializerMethodField()

    class Meta:
        model = Paper
        fields = "__all__"

    def get_authors(self, paper):

        context = self.context
        _context_fields = context.get("pap_dps_get_authorships", {})

        authorships = (
            paper.authorships.annotate(
                author_position_order=Case(
                    When(author_position="first", then=Value(1)),
                    When(author_position="middle", then=Value(2)),
                    When(author_position="last", then=Value(3)),
                    output_field=IntegerField(),
                )
            )
            .select_related("author")
            .all()
            .order_by("author_position_order")
        )

        serializer = DynamicAuthorshipSerializer(
            authorships, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_abstract_src_markdown(self, paper):
        try:
            return paper.abstract_src.read().decode("utf-8")
        except Exception:
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
                vote = DynamicVoteSerializer(
                    vote,
                    context=self.context,
                    **_context_fields,
                ).data

            except Vote.DoesNotExist:
                pass

        return vote

    def get_boost_amount(self, paper):
        if paper.purchases.exists():
            return paper.get_boost_amount()
        return 0

    def get_bounties(self, paper):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_bounties", {})
        _select_related_fields = context.get("pap_dps_get_bounties_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_bounties_prefetch", [])
        bounties = (
            paper.unified_document.related_bounties.select_related(
                *_select_related_fields
            )
            .prefetch_related(*_prefetch_related_fields)
            .all()
        )
        serializer = DynamicBountySerializer(
            bounties,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussions(self, paper):
        from django.contrib.contenttypes.models import ContentType

        from paper.services.paper_version_service import PaperService
        from researchhub_comment.serializers import DynamicRhThreadSerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_discussions", {})
        _select_related_fields = context.get("pap_dps_get_discussions_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_discussions_prefetch", [])

        # Get paper service from context or create default instance
        paper_service = context.get("paper_service", PaperService())

        # Get all versions of this paper
        paper_versions = paper_service.get_all_paper_versions(paper.id)

        # Get content type for Paper model
        paper_content_type = ContentType.objects.get_for_model(paper)

        # Get threads for all paper versions
        from researchhub_comment.models import RhCommentThreadModel

        thread_queryset = (
            RhCommentThreadModel.objects.filter(
                content_type=paper_content_type,
                object_id__in=paper_versions.values_list("id", flat=True),
            )
            .select_related(*_select_related_fields)
            .prefetch_related(*_prefetch_related_fields)
        )

        serializer = DynamicRhThreadSerializer(
            thread_queryset,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussion_aggregates(self, paper):
        from django.contrib.contenttypes.models import ContentType

        from paper.services.paper_version_service import PaperService
        from researchhub_comment.models import RhCommentThreadModel

        # Get paper service from context or create default instance
        paper_service = self.context.get("paper_service", PaperService())

        # Get all versions of this paper
        paper_versions = paper_service.get_all_paper_versions(paper.id)

        # Get content type for Paper model
        paper_content_type = ContentType.objects.get_for_model(paper)

        # Get threads for all paper versions
        thread_queryset = RhCommentThreadModel.objects.filter(
            content_type=paper_content_type,
            object_id__in=paper_versions.values_list("id", flat=True),
        )

        return thread_queryset.get_discussion_aggregates(paper)

    def get_hubs(self, paper):
        context = self.context
        context["unified_document"] = paper.unified_document
        _context_fields = context.get("pap_dps_get_hubs", {})

        serializer = DynamicHubSerializer(
            paper.unified_document.hubs,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_first_preview(self, paper):
        context = self.context

        # If we don't show the PDFs on the paper page, we shouldn't have previews either
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )
        if (
            not self.get_pdf_copyright_allows_display(paper)
            and exclude_copyrighted_content
        ):
            return None

        _context_fields = context.get("pap_dps_get_first_preview", {})
        if paper.figures.exists():
            # Using prefetches to filter by figure preview
            # Slicing with [0] because .first() does not use prefetch cache
            serializer = DynamicFigureSerializer(
                paper.figures.all()[0], context=context, **_context_fields
            )
            return serializer.data
        return None

    def get_purchases(self, paper):
        from purchase.serializers import DynamicPurchaseSerializer

        context = self.context
        _context_fields = context.get("pap_dps_get_purchases", {})
        _select_related_fields = context.get("pap_dps_get_purchases_select", [])
        _prefetch_related_fields = context.get("pap_dps_get_purchases_prefetch", [])
        serializer = DynamicPurchaseSerializer(
            paper.purchases.filter(purchase_type=Purchase.BOOST)
            .select_related(*_select_related_fields)
            .prefetch_related(*_prefetch_related_fields),
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

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

    def get_pdf_copyright_allows_display(self, paper):
        return pdf_copyright_allows_display(paper)

    def get_file(self, paper):
        if not paper.file:
            return None

        # Don't return copyrighted content by default, but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.file.url
        return None

    def get_pdf_url(self, paper):
        if not paper.pdf_url:
            return None

        # Don't return copyrighted content by default, but enable override for specific cases
        exclude_copyrighted_content = self.context.get(
            "exclude_copyrighted_content", True
        )

        if not exclude_copyrighted_content or self.get_pdf_copyright_allows_display(
            paper
        ):
            return paper.pdf_url
        return None

    def get_version(self, paper):
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
            return paper_version.version
        except PaperVersion.DoesNotExist:
            return 1

    def get_version_list(self, paper) -> list:
        try:
            paper_version = PaperVersion.objects.get(paper=paper)
        except PaperVersion.DoesNotExist:
            return [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                }
            ]

        paper_versions = (
            PaperVersion.objects.filter(
                original_paper_id=paper_version.original_paper_id
            )
            .select_related("paper")
            .order_by("version")
        )
        latest_version = paper_versions.last()

        # Return a list of version pointing to the paper_id
        return [
            {
                "version": version.version,
                "paper_id": version.paper.id,
                "publication_status": version.publication_status,
                "published_date": (
                    version.paper.paper_publish_date.strftime("%Y-%m-%d")
                    if version.paper.paper_publish_date
                    else None
                ),
                "message": version.message,
                "is_latest": version.version == latest_version.version,
                "is_version_of_record": (
                    version.version == latest_version.version
                    and version.publication_status == PaperVersion.PUBLISHED
                ),
            }
            for version in paper_versions
        ]


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
