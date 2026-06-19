from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from purchase.related_models.constants.currency import USD
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_hub_editor, create_random_authenticated_user
from utils.test_helpers import AWSMockTestCase


class GrantApplicationVisibilityTests(AWSMockTestCase):
    """DynamicGrantSerializer.get_applications hides private applications from
    users who aren't allowed to see them.

    Private preregistration applications are visible to the grant owner, the
    applicant themselves, and site moderators / hub editors — mirroring
    ResearchhubPost.visible_to. Everyone else (outsiders, anonymous) only sees
    public applications.
    """

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

        self.owner = create_random_authenticated_user("grant_owner")
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.editor, _ = create_hub_editor("hub_editor", "applications-hub")
        self.applicant = create_random_authenticated_user("applicant")
        self.outsider = create_random_authenticated_user("outsider")

        grant_post = create_post(created_by=self.owner, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=grant_post.unified_document,
            amount=1000,
            currency=USD,
            organization="Org",
            description="desc",
        )

        self.public_post = create_post(
            title="Public", created_by=self.applicant, document_type=PREREGISTRATION
        )
        self.private_post = create_post(
            title="Private", created_by=self.applicant, document_type=PREREGISTRATION
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save()

        for post in (self.public_post, self.private_post):
            GrantApplication.objects.create(
                grant=self.grant,
                preregistration_post=post,
                applicant=self.applicant,
            )

    def _visible_post_ids(self, viewer):
        request = self.factory.get("/")
        request.user = viewer if viewer is not None else AnonymousUser()
        serializer = DynamicGrantSerializer(
            self.grant,
            _include_fields=["id", "applications"],
            context={"request": request},
        )
        return {
            app["preregistration_post_id"] for app in serializer.data["applications"]
        }

    def test_owner_sees_private_application(self):
        ids = self._visible_post_ids(self.owner)
        self.assertIn(self.public_post.id, ids)
        self.assertIn(self.private_post.id, ids)

    def test_moderator_sees_private_application(self):
        ids = self._visible_post_ids(self.moderator)
        self.assertIn(self.public_post.id, ids)
        self.assertIn(self.private_post.id, ids)

    def test_hub_editor_sees_private_application(self):
        ids = self._visible_post_ids(self.editor)
        self.assertIn(self.public_post.id, ids)
        self.assertIn(self.private_post.id, ids)

    def test_applicant_sees_own_private_application(self):
        ids = self._visible_post_ids(self.applicant)
        self.assertIn(self.public_post.id, ids)
        self.assertIn(self.private_post.id, ids)

    def test_outsider_only_sees_public_application(self):
        ids = self._visible_post_ids(self.outsider)
        self.assertIn(self.public_post.id, ids)
        self.assertNotIn(self.private_post.id, ids)

    def test_anonymous_only_sees_public_application(self):
        ids = self._visible_post_ids(None)
        self.assertIn(self.public_post.id, ids)
        self.assertNotIn(self.private_post.id, ids)

    def test_pending_proposal_hidden_from_all_viewers(self):
        # Arrange
        pending_post = create_post(
            title="Pending", created_by=self.applicant, document_type=PREREGISTRATION
        )
        pending_post.unified_document.status = ResearchhubUnifiedDocument.PENDING
        pending_post.unified_document.save(update_fields=["status"])
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=pending_post,
            applicant=self.applicant,
        )

        # Act + Assert
        for viewer in (
            self.owner,
            self.moderator,
            self.editor,
            self.applicant,
            self.outsider,
            None,
        ):
            with self.subTest(viewer=getattr(viewer, "username", "anonymous")):
                ids = self._visible_post_ids(viewer)
                self.assertNotIn(pending_post.id, ids)
