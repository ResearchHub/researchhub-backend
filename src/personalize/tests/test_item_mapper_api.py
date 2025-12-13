import json

from django.test import TestCase

from hub.models import Hub
from personalize.services.item_mapper import ItemMapper
from personalize.tests.helpers import (
    create_batch_data,
    create_hub_with_namespace,
    create_prefetched_paper,
)


class ApiItemMappingTests(TestCase):
    def test_api_format_has_itemId_and_properties(self):
        paper = create_prefetched_paper(title="Test Paper")
        mapper = ItemMapper()
        batch_data = create_batch_data()

        result = mapper.map_to_api_item(
            paper,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        self.assertIn("itemId", result)
        self.assertIn("properties", result)
        self.assertEqual(len(result.keys()), 2)
        self.assertIsInstance(result["itemId"], str)

    def test_api_properties_is_json_string(self):
        paper = create_prefetched_paper(title="Test Paper")
        mapper = ItemMapper()
        batch_data = create_batch_data()

        result = mapper.map_to_api_item(
            paper,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        self.assertIsInstance(result["properties"], str)

        properties = json.loads(result["properties"])
        self.assertIsInstance(properties, dict)

    def test_api_keys_are_camelCase(self):
        paper = create_prefetched_paper(title="Test Paper")
        mapper = ItemMapper()
        batch_data = create_batch_data()

        result = mapper.map_to_api_item(
            paper,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        properties = json.loads(result["properties"])

        expected_camel_case_keys = [
            "itemType",
            "creationTimestamp",
            "upvoteScore",
            "citationCountTotal",
            "hasActiveBounty",
            "bountyHasSolutions",
        ]

        for key in expected_camel_case_keys:
            self.assertIn(key, properties, f"{key} should be in properties")

        uppercase_keys = [k for k in properties.keys() if k.isupper() or "_" in k]
        self.assertEqual(
            len(uppercase_keys),
            0,
            f"Found uppercase/snake_case keys: {uppercase_keys}",
        )

    def test_api_booleans_are_strings(self):
        paper = create_prefetched_paper(title="Test Paper")
        mapper = ItemMapper()

        bounty_data = {"has_active_bounty": True, "has_solutions": False}
        proposal_data = {"is_open": True, "has_funders": False}
        rfp_data = {"is_open": False, "has_applicants": False}

        result = mapper.map_to_api_item(
            paper,
            bounty_data=bounty_data,
            proposal_data=proposal_data,
            rfp_data=rfp_data,
            review_count_data={},
        )

        properties = json.loads(result["properties"])

        self.assertEqual(properties["hasActiveBounty"], "True")
        self.assertEqual(properties["bountyHasSolutions"], "False")
        self.assertEqual(properties["proposalIsOpen"], "True")
        self.assertEqual(properties["proposalHasFunders"], "False")

        self.assertIsInstance(properties["hasActiveBounty"], str)
        self.assertIsInstance(properties["bountyHasSolutions"], str)

    def test_api_excludes_ITEM_ID_from_properties(self):
        paper = create_prefetched_paper(title="Test Paper")
        mapper = ItemMapper()
        batch_data = create_batch_data()

        result = mapper.map_to_api_item(
            paper,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        self.assertEqual(result["itemId"], str(paper.id))

        properties = json.loads(result["properties"])
        self.assertNotIn("ITEM_ID", properties)
        self.assertNotIn("itemId", properties)

    def test_api_includes_journal_hub_id(self):
        """JOURNAL_HUB_ID should be included as journalHubId in API format."""
        journal_hub = create_hub_with_namespace("Nature", Hub.Namespace.JOURNAL)
        paper = create_prefetched_paper(title="Test Paper", hubs=[journal_hub])
        mapper = ItemMapper()
        batch_data = create_batch_data()

        result = mapper.map_to_api_item(
            paper,
            bounty_data=batch_data["bounty"],
            proposal_data=batch_data["proposal"],
            rfp_data=batch_data["rfp"],
            review_count_data=batch_data["review_count"],
        )

        properties = json.loads(result["properties"])
        self.assertIn("journalHubId", properties)
        self.assertEqual(properties["journalHubId"], str(journal_hub.id))
