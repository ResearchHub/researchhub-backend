"""
Unit tests for grant search functionality with Request For Proposals prefix handling.
"""

from django.test import TestCase

from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from search.documents.post import PostDocument
from user.tests.helpers import create_random_default_user


class GrantSearchTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("test_user")

    def test_strip_rfp_prefix_method(self):
        """Test the _strip_rfp_prefix method with various RFP prefix patterns"""
        post_doc = PostDocument()

        test_cases = [
            # (input_title, expected_output)
            ("Request For Proposals: AI Research Grant", "AI Research Grant"),
            ("Request for Proposals: Machine Learning Study", "Machine Learning Study"),
            ("RFP: Data Science Initiative", "Data Science Initiative"),
            ("Request for proposals: Climate Research", "Climate Research"),
            ("Request For Proposals AI Grant", "AI Grant"),
            ("RFP Data Science Project", "Data Science Project"),
            ("Regular Grant Title", "Regular Grant Title"),  # No prefix
            ("", ""),  # Empty string
            ("Request For Proposals", ""),  # Only prefix
        ]

        for input_title, expected_output in test_cases:
            with self.subTest(input_title=input_title):
                result = post_doc._strip_rfp_prefix(input_title)
                self.assertEqual(result, expected_output)

    def test_prepare_suggestion_phrases_for_grant_with_rfp_prefix(self):
        """Test that grant posts with RFP prefix get both original and stripped title"""
        # Create a grant post with RFP prefix
        grant_post = create_post(
            title="Request For Proposals: AI Research Grant",
            created_by=self.user,
            document_type=GRANT,
        )

        post_doc = PostDocument()
        result = post_doc.prepare_suggestion_phrases(grant_post)

        # Should contain both original and stripped titles
        phrases = result["input"]
        self.assertIn("Request For Proposals: AI Research Grant", phrases)
        self.assertIn("AI Research Grant", phrases)

        # Should also contain individual words from both versions
        self.assertIn("Request", phrases)
        self.assertIn("AI", phrases)
        self.assertIn("Research", phrases)
        self.assertIn("Grant", phrases)
        # Note: "Proposals" might not be present due to word splitting behavior

    def test_prepare_suggestion_phrases_for_grant_without_rfp_prefix(self):
        """Test that grant posts without RFP prefix work normally"""
        # Create a grant post without RFP prefix
        grant_post = create_post(
            title="AI Research Grant", created_by=self.user, document_type=GRANT
        )

        post_doc = PostDocument()
        result = post_doc.prepare_suggestion_phrases(grant_post)

        # Should contain the original title
        phrases = result["input"]
        self.assertIn("AI Research Grant", phrases)

        # Should not contain a stripped version since no prefix was found
        # (the _strip_rfp_prefix method returns original if no prefix found)
        self.assertEqual(phrases.count("AI Research Grant"), 1)

    def test_prepare_suggestion_phrases_for_non_grant_post(self):
        """Test that non-grant posts are not affected by the RFP prefix logic"""
        # Create a discussion post with RFP-like title
        discussion_post = create_post(
            title="Request For Proposals: Discussion Topic",
            created_by=self.user,
            document_type="DISCUSSION",
        )

        post_doc = PostDocument()
        result = post_doc.prepare_suggestion_phrases(discussion_post)

        # Should only contain the original title, no stripping
        phrases = result["input"]
        self.assertIn("Request For Proposals: Discussion Topic", phrases)
        self.assertNotIn("Discussion Topic", phrases)  # Should not be stripped

    def test_rfp_prefix_patterns_comprehensive(self):
        """Test all RFP prefix patterns comprehensively"""
        post_doc = PostDocument()

        test_cases = [
            # Various RFP prefix formats
            ("Request For Proposals: Grant Title", "Grant Title"),
            ("Request for Proposals: Grant Title", "Grant Title"),
            ("RFP: Grant Title", "Grant Title"),
            ("Request for proposals: Grant Title", "Grant Title"),
            ("Request For Proposals Grant Title", "Grant Title"),
            ("Request for Proposals Grant Title", "Grant Title"),
            ("RFP Grant Title", "Grant Title"),
            ("Request for proposals Grant Title", "Grant Title"),
            # Edge cases
            ("Request For Proposals:", ""),
            ("RFP:", ""),
            ("Request For Proposals", ""),
            ("RFP", ""),
            # No prefix cases
            ("Regular Grant Title", "Regular Grant Title"),
            ("AI Research Grant", "AI Research Grant"),
        ]

        for input_title, expected_output in test_cases:
            with self.subTest(input_title=input_title):
                result = post_doc._strip_rfp_prefix(input_title)
                self.assertEqual(result, expected_output)

    def test_suggestion_phrases_weight_assignment(self):
        """Test that suggestion phrases maintain proper weight assignment"""
        grant_post = create_post(
            title="Request For Proposals: AI Research Grant",
            created_by=self.user,
            document_type=GRANT,
        )

        post_doc = PostDocument()
        result = post_doc.prepare_suggestion_phrases(grant_post)

        # Should have weight assigned
        self.assertIn("weight", result)
        self.assertIsInstance(result["weight"], int)
        self.assertGreaterEqual(result["weight"], 1)

        # Should have input phrases
        self.assertIn("input", result)
        self.assertIsInstance(result["input"], list)
        self.assertGreater(len(result["input"]), 0)
