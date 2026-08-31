from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from note.models import Note
from note.tests.helpers import create_note
from purchase.models import Grant
from research_ai.services.notebook_chat.grant_tools import (
    GET_GRANT_DETAILS,
    READ_SELECTED_RFP,
    SEARCH_GRANTS,
    SET_SELECTED_RFP,
    GrantSearchToolset,
    SelectedRFPToolset,
)
from researchhub_access_group.constants import ADMIN, VIEWER
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

    def _details(self, user, grant_id):
        toolset = GrantSearchToolset(user=user).as_toolset()
        result, stop = toolset.dispatch(GET_GRANT_DETAILS, {"grant_id": grant_id})
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
        self.assertNotIn("description", item)
        self.assertNotIn("post_content", item)

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

    def test_search_returns_compact_summary_when_only_the_backing_post_matches(self):
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
        self.assertTrue(item["summary"].startswith("Supports single-cell proteomics"))
        self.assertLessEqual(len(item["summary"]), 280)
        self.assertNotIn("post_content", item)

    def test_grant_details_returns_full_text_on_demand(self):
        # Arrange
        grant = self._grant(
            title="Rare Disease Methods",
            description="Structured program summary.",
            post_content="Full RFP requirements for single-cell proteomics.",
        )

        # Act
        result = self._details(self.user, grant.id)

        # Assert
        self.assertEqual(result["id"], grant.id)
        self.assertEqual(result["description"], "Structured program summary.")
        self.assertIn("Full RFP requirements", result["rfp_text"])

    def test_grant_details_rechecks_visibility(self):
        # Arrange
        private = self._grant(
            title="Private Methods Call",
            description="Not public.",
            is_public=False,
        )

        # Act
        owner_result = self._details(self.owner, private.id)
        other_result = self._details(self.user, private.id)

        # Assert
        self.assertEqual(owner_result["id"], private.id)
        self.assertEqual(
            other_result,
            {"error": f"grant {private.id} not found or not accessible"},
        )

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


class SetSelectedRFPToolTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("set_rfp_user")
        self.owner = create_random_authenticated_user("set_rfp_owner")
        self.note, _ = create_note(self.user, organization=None)
        self.note.document_type = PREREGISTRATION
        self.note.save(update_fields=["document_type"])
        self.permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )

    def _grant(self, *, title="Reproducibility RFP", status=Grant.OPEN, is_public=True):
        post = create_post(
            created_by=self.owner,
            document_type=GRANT,
            title=title,
        )
        post.slug = title.lower().replace(" ", "-")
        post.save(update_fields=["slug"])
        post.unified_document.is_public = is_public
        post.unified_document.save(update_fields=["is_public"])
        return Grant.objects.create(
            created_by=self.owner,
            unified_document=post.unified_document,
            short_title=title,
            organization="Research Foundation",
            description="Funding for reproducible research.",
            amount=Decimal("75000.00"),
            currency="USD",
            status=status,
            end_date=timezone.now() + timedelta(days=30),
        )

    def _set(self, grant_id, user=None):
        toolset = SelectedRFPToolset(
            note=self.note, user=self.user if user is None else user
        ).as_toolset()
        result, stop = toolset.dispatch(SET_SELECTED_RFP, {"grant_id": grant_id})
        self.assertFalse(stop)
        return result

    def test_selects_replaces_and_clears_the_rfp(self):
        # Arrange
        first = self._grant(title="First RFP")
        second = self._grant(title="Second RFP")

        # Act
        selected = self._set(first.id)
        replaced = self._set(second.id)
        self.note.refresh_from_db()
        replaced_grant_id = self.note.selected_grant_id
        cleared = self._set(None)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(selected["selected_rfp"]["id"], first.id)
        self.assertEqual(selected["selected_rfp"]["title"], "First RFP")
        self.assertIn("/grant/", selected["selected_rfp"]["url"])
        self.assertTrue(selected["saved"])
        self.assertEqual(replaced["selected_rfp"]["id"], second.id)
        self.assertEqual(replaced_grant_id, second.id)
        self.assertIsNone(cleared["selected_rfp"])
        self.assertIsNone(self.note.selected_grant_id)

    def test_refuses_a_grant_that_stopped_accepting_applications(self):
        # Arrange
        closed = self._grant(status=Grant.CLOSED)

        # Act
        result = self._set(closed.id)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(
            result, {"error": "Grant is no longer accepting applications."}
        )
        self.assertIsNone(self.note.selected_grant_id)

    def test_refuses_a_grant_the_user_cannot_view(self):
        # Arrange
        private = self._grant(is_public=False)

        # Act
        result = self._set(private.id)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(
            result, {"error": f"grant {private.id} not found or not accessible"}
        )
        self.assertIsNone(self.note.selected_grant_id)

    def test_refuses_a_user_without_edit_permission(self):
        # Arrange: a viewer can read the note but must not change its RFP.
        grant = self._grant()
        self.permission.access_type = VIEWER
        self.permission.save(update_fields=["access_type"])

        # Act
        result = self._set(grant.id)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(
            result, {"error": "no permission to change this note's selected RFP"}
        )
        self.assertIsNone(self.note.selected_grant_id)

    def test_refuses_a_published_note(self):
        # Arrange
        grant = self._grant()
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        post.note = self.note
        post.save(update_fields=["note"])

        # Act
        result = self._set(grant.id)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(result, {"error": "Published notes cannot change grants."})
        self.assertIsNone(self.note.selected_grant_id)

    def test_refuses_a_non_preregistration_note(self):
        # Arrange
        grant = self._grant()
        self.note.document_type = "NOTE"
        self.note.save(update_fields=["document_type"])

        # Act
        result = self._set(grant.id)
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(result, {"error": "this preregistration is not accessible"})
        self.assertIsNone(self.note.selected_grant_id)

    def test_rejects_a_malformed_grant_id_rather_than_clearing(self):
        # Arrange
        grant = self._grant()
        self._set(grant.id)

        # Act
        result = self._set("not-an-id")
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(result, {"error": "grant_id must be a grant id or null"})
        self.assertEqual(self.note.selected_grant_id, grant.id)

    def test_rejects_an_omitted_grant_id_rather_than_clearing(self):
        # Arrange: dispatch does not enforce the input schema, so an argument
        # object with no grant_id reaches the handler; only an explicit null
        # may clear a selection.
        grant = self._grant()
        self._set(grant.id)
        toolset = SelectedRFPToolset(note=self.note, user=self.user).as_toolset()

        # Act
        result, _stop = toolset.dispatch(SET_SELECTED_RFP, {})
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(
            result,
            {"error": "grant_id is required; pass null to clear the selection"},
        )
        self.assertEqual(self.note.selected_grant_id, grant.id)

    def test_notifies_the_notebook_that_the_note_changed(self):
        # Arrange: a selection writes no NoteContent, so the org room push is
        # all that tells an open notebook the RFP changed.
        self.note.organization = self.user.organization
        self.note.save(update_fields=["organization"])
        grant = self._grant()

        # Act
        with patch.object(Note, "notify_note_updated_title") as notify:
            result = self._set(grant.id)

        # Assert
        self.assertTrue(result["saved"])
        notify.assert_called_once_with()

    def test_refuses_an_unauthenticated_caller(self):
        # Arrange
        grant = self._grant()

        # Act
        result = self._set(grant.id, user=AnonymousUser())
        self.note.refresh_from_db()

        # Assert
        self.assertEqual(result, {"error": "this preregistration is not accessible"})
        self.assertIsNone(self.note.selected_grant_id)

    def test_falls_back_to_the_post_title_when_the_grant_has_no_short_title(self):
        # Arrange: the title reported back is what the model and the activity
        # feed show for the selected RFP.
        grant = self._grant(title="Untitled Program RFP")
        grant.short_title = ""
        grant.save(update_fields=["short_title"])

        # Act
        result = self._set(grant.id)

        # Assert
        self.assertEqual(result["selected_rfp"]["title"], "Untitled Program RFP")

    def test_rejects_grant_ids_that_are_not_whole_numbers(self):
        # Arrange: int() would truncate 1.9 and coerce True to 1, selecting
        # grant 1 -- an unrelated RFP the user never asked for.
        grant = self._grant()
        self._set(grant.id)

        # Act
        results = [self._set(value) for value in (1.9, True, "1.9", "  ")]
        self.note.refresh_from_db()

        # Assert
        for result in results:
            self.assertEqual(result, {"error": "grant_id must be a grant id or null"})
        self.assertEqual(self.note.selected_grant_id, grant.id)

    def test_accepts_a_grant_id_sent_as_a_digit_string(self):
        # Arrange
        grant = self._grant()

        # Act
        result = self._set(str(grant.id))

        # Assert
        self.assertEqual(result["selected_rfp"]["id"], grant.id)
