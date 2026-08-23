from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from note.tests.helpers import create_note
from purchase.models import Grant
from research_ai.services.notebook_chat.grant_tools import (
    READ_SELECTED_RFP,
    SEARCH_GRANTS,
    GrantSearchToolset,
    SelectedRFPToolset,
)
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class GrantSearchToolsetTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("grant_search_user")
        self.owner = create_random_authenticated_user("grant_search_owner")

    def _grant(
        self,
        *,
        title,
        description,
        status=Grant.OPEN,
        is_public=True,
        end_date=None,
        post_content=None,
        short_title=None,
    ):
        post = create_post(
            created_by=self.owner,
            document_type=GRANT,
            title=title,
            renderable_text=description if post_content is None else post_content,
        )
        post.slug = title.lower().replace(" ", "-")
        post.save(update_fields=["slug"])
        post.unified_document.is_public = is_public
        post.unified_document.save(update_fields=["is_public"])
        return Grant.objects.create(
            created_by=self.owner,
            unified_document=post.unified_document,
            short_title=title if short_title is None else short_title,
            organization="Research Foundation",
            description=description,
            amount=Decimal("50000.00"),
            currency="USD",
            status=status,
            end_date=end_date,
        )

    def _search(self, user, query):
        toolset = GrantSearchToolset(user=user).as_toolset()
        result, stop = toolset.dispatch(SEARCH_GRANTS, {"query": query})
        self.assertFalse(stop)
        return result

    def test_search_returns_only_matching_active_visible_grants(self):
        # Arrange
        matching = self._grant(
            title="Neural Biomarker Discovery",
            description="Funding for neuroscience biomarker validation.",
            end_date=timezone.now() + timedelta(days=30),
        )
        self._grant(
            title="Neural Biomarker Closed Call",
            description="An old neuroscience opportunity.",
            status=Grant.CLOSED,
        )
        self._grant(
            title="Neural Biomarker Expired Call",
            description="An expired neuroscience opportunity.",
            end_date=timezone.now() - timedelta(days=1),
        )
        self._grant(
            title="Private Neural Biomarker Call",
            description="A private neuroscience opportunity.",
            is_public=False,
        )
        self._grant(
            title="Marine Ecology Fieldwork",
            description="Funding for coastal biodiversity surveys.",
        )

        # Act
        result = self._search(self.user, "neural biomarker")

        # Assert
        self.assertEqual([item["id"] for item in result["grants"]], [matching.id])
        item = result["grants"][0]
        self.assertEqual(item["title"], "Neural Biomarker Discovery")
        self.assertEqual(item["amount"], "50000.00")
        self.assertEqual(item["currency"], "USD")
        post_id = matching.unified_document.posts.first().id
        self.assertIn(f"/grant/{post_id}/", item["url"])

    def test_search_respects_private_grant_owner_visibility(self):
        # Arrange
        private = self._grant(
            title="Private Quantum Methods Call",
            description="Private funding for quantum sensing methods.",
            is_public=False,
        )

        # Act
        owner_result = self._search(self.owner, "quantum sensing")
        other_result = self._search(self.user, "quantum sensing")

        # Assert
        self.assertEqual([item["id"] for item in owner_result["grants"]], [private.id])
        self.assertEqual(other_result["grants"], [])

    def test_search_returns_content_when_only_the_backing_post_matches(self):
        # Arrange
        post_content = "Supports single-cell proteomics in rare diseases. " + (
            "x" * 4000
        )
        matching = self._grant(
            title="Emerging Methods Award",
            short_title="",
            description="Funding for reproducible experimental research.",
            post_content=post_content,
        )

        # Act
        result = self._search(self.user, "single-cell proteomics")

        # Assert
        self.assertEqual([item["id"] for item in result["grants"]], [matching.id])
        item = result["grants"][0]
        self.assertEqual(item["title"], "Emerging Methods Award")
        self.assertEqual(item["post_content"], post_content[:3000])

    def test_search_requires_a_bounded_query(self):
        # Arrange
        toolset = GrantSearchToolset(user=self.user).as_toolset()

        # Act
        missing, _stop = toolset.dispatch(SEARCH_GRANTS, {"query": "  "})
        oversized, _stop = toolset.dispatch(
            SEARCH_GRANTS,
            {"query": "x" * 501},
        )

        # Assert
        self.assertEqual(missing, {"error": "query is required"})
        self.assertEqual(oversized, {"error": "query exceeds 500 characters"})


class SelectedRFPToolsetTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("selected_rfp_user")
        self.owner = create_random_authenticated_user("selected_rfp_owner")
        self.note, _ = create_note(self.user, organization=None)
        self.note.document_type = PREREGISTRATION
        self.note.save(update_fields=["document_type"])
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )

    def _grant(self, *, is_public=True):
        post = create_post(
            created_by=self.owner,
            document_type=GRANT,
            title="Reproducibility RFP",
        )
        post.slug = "reproducibility-rfp"
        post.discussion_src.save(
            "rfp.md",
            ContentFile(b"# Full call\nApplicants must publish their methods."),
        )
        post.save(update_fields=["slug"])
        post.unified_document.is_public = is_public
        post.unified_document.save(update_fields=["is_public"])
        return Grant.objects.create(
            created_by=self.owner,
            unified_document=post.unified_document,
            short_title="Reproducibility RFP",
            organization="Research Foundation",
            description="Funding for reproducible research.",
            amount=Decimal("75000.00"),
            currency="USD",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

    def _read(self):
        toolset = SelectedRFPToolset(note=self.note, user=self.user).as_toolset()
        result, stop = toolset.dispatch(READ_SELECTED_RFP, {})
        self.assertFalse(stop)
        return result

    def test_reads_selected_rfp_full_text_and_terms(self):
        # Arrange
        grant = self._grant()
        self.note.selected_grant = grant
        self.note.save(update_fields=["selected_grant"])

        # Act
        result = self._read()

        # Assert
        self.assertEqual(result["id"], grant.id)
        self.assertEqual(result["title"], "Reproducibility RFP")
        self.assertEqual(result["amount"], "75000.00")
        self.assertIn("Funding for reproducible research.", result["rfp_text"])
        self.assertIn("Applicants must publish their methods.", result["rfp_text"])
        self.assertIn("/grant/", result["url"])

    def test_reports_when_preregistration_has_no_selected_rfp(self):
        # Act
        result = self._read()

        # Assert
        self.assertEqual(result, {"error": "this preregistration has no selected RFP"})

    def test_does_not_expose_an_rfp_the_user_can_no_longer_view(self):
        # Arrange: model a grant becoming private after it was selected.
        grant = self._grant(is_public=False)
        self.note.selected_grant = grant
        self.note.save(update_fields=["selected_grant"])

        # Act
        result = self._read()

        # Assert
        self.assertEqual(result, {"error": "selected RFP not found or not accessible"})

    def test_refuses_a_non_preregistration_note(self):
        # Arrange
        grant = self._grant()
        self.note.document_type = "NOTE"
        self.note.selected_grant = grant
        self.note.save(update_fields=["document_type", "selected_grant"])

        # Act
        result = self._read()

        # Assert
        self.assertEqual(result, {"error": "selected RFP not found or not accessible"})
