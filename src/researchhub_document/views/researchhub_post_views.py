from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from analytics.tasks import track_revenue_event
from discussion.reaction_views import ReactionViewActionMixin
from hub.models import Hub
from note.related_models.note_model import Note
from purchase.models import Balance, Grant, Purchase
from purchase.related_models.constants.currency import USD
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.grant_create_serializer import GrantCreateSerializer
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from purchase.services.fundraise_service import FundraiseService
from researchhub.settings import CROSSREF_DOI_RSC_FEE, TESTING
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    GRANT,
    POSTS,
    PREREGISTRATION,
    QUESTION,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
)
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    HOT,
    MOST_RSC,
    NEW,
    UPVOTED,
)
from researchhub_document.serializers.researchhub_post_serializer import (
    ResearchhubPostSerializer,
)
from researchhub_document.utils import reset_unified_document_cache
from user.models import User
from user.related_models.author_model import Author
from utils.doi import DOI
from utils.sentry import log_error
from utils.siftscience import SIFT_POST, sift_track
from utils.throttles import THROTTLE_CLASSES

MIN_POST_TITLE_LENGTH = 20
MIN_POST_BODY_LENGTH = 50


class ResearchhubPostViewSet(ReactionViewActionMixin, ModelViewSet):
    ordering = "-created_date"
    queryset = ResearchhubUnifiedDocument.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly, HasDocumentEditingPermission]
    serializer_class = ResearchhubPostSerializer
    throttle_classes = THROTTLE_CLASSES

    @track_event
    def create(self, request, *args, **kwargs):
        return self.upsert_researchhub_posts(request)

    def update(self, request, *args, **kwargs):
        return self.upsert_researchhub_posts(request)

    def get_queryset(self):
        request = self.request
        try:
            query_set = ResearchhubPost.objects.all()
            query_params = request.query_params
            created_by_id = query_params.get("created_by")
            post_id = query_params.get("post_id")
            document_type = query_params.get("document_type")

            if created_by_id is not None:
                query_set = query_set.filter(created_by__id=created_by_id)
            if post_id is not None:
                query_set = query_set.filter(id=post_id)
            if document_type is not None:
                query_set = query_set.filter(document_type=document_type)

            return query_set.order_by("-created_date")
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def upsert_researchhub_posts(self, request):
        try:
            if request.data.get("post_id") is not None:
                return self.update_existing_researchhub_posts(request)
            else:
                return self.create_researchhub_post(request)
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def _check_authors_in_org(self, authors, organization):
        for author_id in authors:
            author = Author.objects.select_related("user").get(id=author_id)
            if not organization.org_has_user(author.user):
                return False
        return True

    @sift_track(SIFT_POST)
    def create_researchhub_post(self, request):
        data = request.data
        authors = data.get("authors", [])
        note_id = data.get("note_id", None)
        document_type = data.get("document_type")
        editor_type = data.get("editor_type")
        title = data.get("title", "")
        assign_doi = data.get("assign_doi", False)
        renderable_text = data.get("renderable_text", "")
        grant_amount = data.get("grant_amount")

        # If a note is provided, check if all given authors are in the same organization
        if note_id is not None:
            note = Note.objects.get(id=note_id)
            organization = note.organization
            if not self._check_authors_in_org(authors, organization):
                return Response(
                    "No permission to create note for organization", status=403
                )

        if type(title) is not str or len(title) < MIN_POST_TITLE_LENGTH:
            return Response(
                {
                    "msg": (
                        f"Title cannot be less than "
                        f"{MIN_POST_TITLE_LENGTH} characters"
                    )
                },
                400,
            )
        elif (
            type(renderable_text) is not str
            or len(renderable_text) < MIN_POST_BODY_LENGTH
        ):
            return Response(
                {
                    "msg": (
                        f"Post body cannot be less than "
                        f"{MIN_POST_BODY_LENGTH} characters"
                    )
                },
                400,
            )

        try:
            with transaction.atomic():
                created_by = request.user
                created_by_author = created_by.author_profile
                doi = DOI() if assign_doi else None

                # logical ordering & not using signals to avoid race-conditions
                access_group = self.create_access_group(request)
                unified_document = self.create_unified_doc(request)
                if access_group is not None:
                    unified_document.access_groups = access_group
                    unified_document.save()

                slug = slugify(title)
                rh_post = ResearchhubPost.objects.create(
                    created_by=created_by,
                    document_type=document_type,
                    doi=doi.doi if doi else None,
                    slug=slug,
                    editor_type=CK_EDITOR if editor_type is None else editor_type,
                    image=data.get("image"),
                    note_id=note_id,
                    prev_version=None,
                    preview_img=data.get("preview_img"),
                    renderable_text=data.get("renderable_text"),
                    title=title,
                    bounty_type=data.get("bounty_type"),
                    unified_document=unified_document,
                )
                file_name = f"RH-POST-{document_type}-USER-{created_by.id}.txt"
                full_src_file = ContentFile(data["full_src"].encode())
                rh_post.authors.set(authors)
                self.add_upvote(created_by, rh_post)

                fundraise = None
                if goal_amount := data.get("fundraise_goal_amount"):
                    serializer = FundraiseCreateSerializer(
                        data={
                            "goal_amount": goal_amount,
                            "goal_currency": data.get("fundraise_goal_currency", USD),
                            "unified_document_id": unified_document.id,
                            "recipient_user_id": created_by.id,
                        }
                    )
                    serializer.is_valid(raise_exception=True)

                    fundraise_service = FundraiseService()
                    try:
                        fundraise = fundraise_service.create_fundraise_with_escrow(
                            user=created_by,
                            unified_document=unified_document,
                            goal_amount=serializer.validated_data["goal_amount"],
                            goal_currency=serializer.validated_data["goal_currency"],
                        )
                    except serializers.ValidationError as e:
                        return Response({"message": str(e)}, status=400)

                grant = None
                if grant_amount := data.get("grant_amount"):
                    grant_data = {
                        "amount": grant_amount,
                        "currency": data.get("grant_currency", USD),
                        "organization": data.get("grant_organization"),
                        "description": data.get("grant_description"),
                        "unified_document_id": unified_document.id,
                        "end_date": data.get("grant_end_date"),
                    }

                    # Only include contact_ids if it's provided and not None
                    grant_contacts = data.get("grant_contacts")
                    if grant_contacts is not None:
                        grant_data["contact_ids"] = grant_contacts

                    grant_serializer = GrantCreateSerializer(data=grant_data)
                    grant_serializer.is_valid(raise_exception=True)

                    # Create grant without contacts first
                    grant = Grant.objects.create(
                        created_by=created_by,
                        unified_document=unified_document,
                        amount=grant_serializer.validated_data["amount"],
                        currency=grant_serializer.validated_data["currency"],
                        organization=grant_serializer.validated_data["organization"],
                        description=grant_serializer.validated_data["description"],
                        end_date=grant_serializer.validated_data.get("end_date"),
                    )

                    # Handle contacts properly - get contact_ids and convert to User objects
                    contact_ids = grant_serializer.validated_data.get("contact_ids", [])
                    if contact_ids:
                        contacts = User.objects.filter(id__in=contact_ids)
                        grant.contacts.set(contacts)
                    else:
                        grant.contacts.clear()

                if not TESTING:
                    if document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                        rh_post.discussion_src.save(file_name, full_src_file)
                    else:
                        rh_post.eln_src.save(file_name, full_src_file)

                if assign_doi:
                    crossref_response = doi.register_doi_for_post(
                        [created_by_author], title, rh_post
                    )
                    if crossref_response.status_code != 200:
                        return Response("Crossref API Failure", status=400)

                reset_unified_document_cache(
                    document_type=[
                        ALL.lower(),
                        POSTS.lower(),
                        PREREGISTRATION.lower(),
                        GRANT.lower(),
                        QUESTION.lower(),
                        BOUNTY.lower(),
                    ],
                    filters=[NEW, MOST_RSC],
                )

                unified_document.update_filters(
                    (
                        FILTER_BOUNTY_OPEN,
                        FILTER_HAS_BOUNTY,
                        SORT_BOUNTY_EXPIRATION_DATE,
                        SORT_BOUNTY_TOTAL_AMOUNT,
                    )
                )

            response_data = ResearchhubPostSerializer(rh_post).data
            response_data["fundraise"] = (
                DynamicFundraiseSerializer(fundraise).data if fundraise else None
            )
            # Set up context for grant serialization including contacts
            grant_context = {
                "pch_dgs_get_created_by": {
                    "_include_fields": (
                        "id",
                        "author_profile",
                        "first_name",
                        "last_name",
                    )
                },
                "pch_dgs_get_contacts": {
                    "_include_fields": (
                        "id",
                        "author_profile",
                        "first_name",
                        "last_name",
                    )
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": (
                        "id",
                        "first_name",
                        "last_name",
                        "created_date",
                        "updated_date",
                        "profile_image",
                        "is_verified",
                    )
                },
            }
            response_data["grant"] = (
                DynamicGrantSerializer(
                    grant,
                    context=grant_context,
                    _include_fields=[
                        "id",
                        "status",
                        "amount",
                        "currency",
                        "organization",
                        "description",
                        "start_date",
                        "end_date",
                        "is_expired",
                        "is_active",
                        "created_by",
                        "contacts",
                    ],
                ).data
                if grant
                else None
            )
            return Response(response_data, status=200)

        except (KeyError, TypeError) as exception:
            log_error(exception)
            return Response({"error": str(exception)}, status=400)

    @sift_track(SIFT_POST, is_update=True)
    def update_existing_researchhub_posts(self, request):
        try:
            data = request.data

            authors = data.get("authors", [])
            rh_post_id = data.get("post_id", None)
            rh_post = ResearchhubPost.objects.get(id=rh_post_id)

            # Check if all given authors are in the same organization
            if rh_post.note_id:
                note = Note.objects.get(id=rh_post.note_id)
                organization = note.organization
                if not self._check_authors_in_org(authors, organization):
                    return Response(
                        "No permission to update post for organization", status=403
                    )

            created_by = request.user
            created_by_author = created_by.author_profile
            hubs = data.get("hubs", None)
            renderable_text = data.get("renderable_text", "")
            title = data.get("title", "")
            assign_doi = data.get("assign_doi", False)
            doi = DOI() if assign_doi else None

            if type(title) is not str or len(title) < MIN_POST_TITLE_LENGTH:
                return Response(
                    {
                        "msg": (
                            f"Title cannot be less than "
                            f"{MIN_POST_TITLE_LENGTH} characters"
                        )
                    },
                    400,
                )
            elif (
                type(renderable_text) is not str
                or len(renderable_text) < MIN_POST_BODY_LENGTH
            ):
                return Response(
                    {
                        "msg": (
                            f"Post body cannot be less than "
                            f"{MIN_POST_BODY_LENGTH} characters"
                        )
                    },
                    400,
                )

            rh_post.doi = doi.doi if doi else rh_post.doi
            rh_post.save(update_fields=["doi"])

            serializer = ResearchhubPostSerializer(
                rh_post, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            post = serializer.instance

            file_name = (
                f'RH-POST-{request.data.get("document_type")}-'
                f"USER-{request.user.id}.txt"
            )
            full_src_file = ContentFile(request.data["full_src"].encode())
            post.discussion_src.save(file_name, full_src_file)

            if type(authors) is list:
                rh_post.authors.set(authors)

            if type(hubs) is list:
                unified_doc = post.unified_document
                unified_doc.hubs.set(hubs)

            reset_unified_document_cache(
                document_type=[
                    ALL.lower(),
                    POSTS.lower(),
                    PREREGISTRATION.lower(),
                    GRANT.lower(),
                    QUESTION.lower(),
                ],
                filters=[NEW, DISCUSSED, UPVOTED, HOT],
            )

            if assign_doi:
                crossref_response = doi.register_doi_for_post(
                    [created_by_author], title, rh_post
                )
                if crossref_response.status_code != 200:
                    return Response("Crossref API Failure", status=400)

            # Handle grant updates
            grant = None
            unified_document = post.unified_document

            # Get existing grant if any
            existing_grant = Grant.objects.filter(
                unified_document=unified_document
            ).first()

            # Only update grants if both grant data is provided AND a grant already exists
            if (grant_amount := data.get("grant_amount")) and existing_grant:
                grant_data = {
                    "amount": grant_amount,
                    "currency": data.get("grant_currency", USD),
                    "organization": data.get("grant_organization"),
                    "description": data.get("grant_description"),
                    "unified_document_id": unified_document.id,
                    "end_date": data.get("grant_end_date"),
                }

                # Only include contact_ids if it's provided and not None
                grant_contacts = data.get("grant_contacts")
                if grant_contacts is not None:
                    grant_data["contact_ids"] = grant_contacts

                grant_serializer = GrantCreateSerializer(data=grant_data)
                grant_serializer.is_valid(raise_exception=True)

                # Update existing grant
                existing_grant.amount = grant_serializer.validated_data["amount"]
                existing_grant.currency = grant_serializer.validated_data["currency"]
                existing_grant.organization = grant_serializer.validated_data[
                    "organization"
                ]
                existing_grant.description = grant_serializer.validated_data[
                    "description"
                ]
                existing_grant.end_date = grant_serializer.validated_data.get(
                    "end_date"
                )

                # Handle contacts properly - get contact_ids and convert to User objects
                contact_ids = grant_serializer.validated_data.get("contact_ids", [])
                if contact_ids:
                    contacts = User.objects.filter(id__in=contact_ids)
                    existing_grant.contacts.set(contacts)
                else:
                    existing_grant.contacts.clear()

                existing_grant.save()
                grant = existing_grant
            else:
                # No grant data provided or no existing grant, preserve existing grant
                grant = existing_grant

            response_data = serializer.data
            # Set up context for grant serialization including contacts
            grant_context = {
                "pch_dgs_get_created_by": {
                    "_include_fields": (
                        "id",
                        "author_profile",
                        "first_name",
                        "last_name",
                    )
                },
                "pch_dgs_get_contacts": {
                    "_include_fields": (
                        "id",
                        "author_profile",
                        "first_name",
                        "last_name",
                    )
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": (
                        "id",
                        "first_name",
                        "last_name",
                        "created_date",
                        "updated_date",
                        "profile_image",
                        "is_verified",
                    )
                },
            }
            response_data["grant"] = (
                DynamicGrantSerializer(
                    grant,
                    context=grant_context,
                    _include_fields=[
                        "id",
                        "status",
                        "amount",
                        "currency",
                        "organization",
                        "description",
                        "start_date",
                        "end_date",
                        "is_expired",
                        "is_active",
                        "created_by",
                        "contacts",
                    ],
                ).data
                if grant
                else None
            )
            return Response(response_data, status=200)

        except (KeyError, TypeError) as exception:
            log_error(exception)
            return Response({"error": str(exception)}, status=400)

    def create_access_group(self, request):
        return None

    def create_unified_doc(self, request):
        try:
            request_data = request.data
            hubs = Hub.objects.filter(id__in=request_data.get("hubs", [])).all()
            uni_doc = ResearchhubUnifiedDocument.objects.create(
                document_type=request_data.get("document_type"),
            )
            uni_doc.hubs.add(*hubs)
            uni_doc.save()
            return uni_doc
        except (KeyError, TypeError) as exception:
            print("create_unified_doc: ", exception)


def charge_doi_fee(created_by, rh_post):
    purchase = Purchase.objects.create(
        user=created_by,
        content_type=ContentType.objects.get(model="researchhubpost"),
        object_id=rh_post.id,
        purchase_method=Purchase.OFF_CHAIN,
        purchase_type=Purchase.DOI,
        amount=CROSSREF_DOI_RSC_FEE,
        paid_status=Purchase.PAID,
    )
    Balance.objects.create(
        user=created_by,
        content_type=ContentType.objects.get_for_model(purchase),
        object_id=purchase.id,
        amount=-CROSSREF_DOI_RSC_FEE,
    )

    # Track in Amplitude
    track_revenue_event.apply_async(
        (
            created_by.id,
            "DOI_FEE",
            str(CROSSREF_DOI_RSC_FEE),
            None,
            "OFF_CHAIN",
        ),
        priority=1,
    )
