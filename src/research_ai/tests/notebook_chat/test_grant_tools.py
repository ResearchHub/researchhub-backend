from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from purchase.models import Grant
from research_ai.services.notebook_chat.grant_tools import (
    SEARCH_GRANTS,
    GrantSearchToolset,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
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
    ):
        post = create_post(
            created_by=self.owner,
            document_type=GRANT,
            title=title,
            renderable_text=description,
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
