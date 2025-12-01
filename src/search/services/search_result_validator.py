"""
Validation utilities for search result enrichment.
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SearchResultValidator:
    """Validates and cleans nested structures in search results."""

    @staticmethod
    def validate_hub_dict(hub: dict[str, Any] | None) -> dict[str, Any] | None:
        return SearchResultValidator._validate_id_name_slug_dict(
            hub, ["id", "name", "slug"]
        )

    @staticmethod
    def validate_journal_dict(
        journal: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not journal or not isinstance(journal, dict):
            return None

        journal_id = journal.get("id")
        name = journal.get("name")
        slug = journal.get("slug")

        if journal_id is None or name is None or slug is None:
            return None

        try:
            journal_id = int(journal_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(slug, str) or not slug.strip():
            return None

        return {
            "id": journal_id,
            "name": name.strip(),
            "slug": slug.strip(),
            "image": journal.get("image"),
            "description": journal.get("description"),
        }

    @staticmethod
    def validate_review_dict(
        review: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not review or not isinstance(review, dict):
            return None

        review_id = review.get("id")
        score = review.get("score")

        if review_id is None or score is None:
            return None

        try:
            review_id = int(review_id)
            score = int(score)
        except (ValueError, TypeError):
            return None

        return {"id": review_id, "score": score, "author": review.get("author")}

    @staticmethod
    def validate_bounty_dict(
        bounty: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not bounty or not isinstance(bounty, dict):
            return None

        bounty_id = bounty.get("id")
        status = bounty.get("status")

        if bounty_id is None or status is None:
            return None

        try:
            bounty_id = int(bounty_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(status, str) or not status.strip():
            return None

        return {
            "id": bounty_id,
            "status": status.strip(),
            "amount": bounty.get("amount", 0),
            "bounty_type": bounty.get("bounty_type"),
            "expiration_date": bounty.get("expiration_date"),
            "contributors": bounty.get("contributors", []),
            "contributions": bounty.get("contributions", []),
        }

    @staticmethod
    def validate_purchase_dict(
        purchase: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not purchase or not isinstance(purchase, dict):
            return None

        purchase_id = purchase.get("id")
        amount = purchase.get("amount")

        if purchase_id is None or amount is None:
            return None

        try:
            purchase_id = int(purchase_id)
            if isinstance(amount, str):
                float(amount)
                amount_str = amount
            else:
                amount_str = str(amount)
        except (ValueError, TypeError):
            return None

        return {"id": purchase_id, "amount": amount_str, "user": purchase.get("user")}

    @staticmethod
    def validate_author_detail_dict(
        author: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not author or not isinstance(author, dict):
            return None

        author_id = author.get("id")
        if author_id is None:
            return None

        try:
            author_id = int(author_id)
        except (ValueError, TypeError):
            return None

        return {
            "id": author_id,
            "first_name": author.get("first_name", ""),
            "last_name": author.get("last_name", ""),
            "profile_image": author.get("profile_image"),
            "headline": author.get("headline"),
            "user": author.get("user"),
        }

    @staticmethod
    def validate_author_dict(
        author: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not author or not isinstance(author, dict):
            return None

        first_name = author.get("first_name", "") or ""
        last_name = author.get("last_name", "") or ""
        full_name = author.get("full_name", "") or ""

        if not full_name and (first_name or last_name):
            full_name = f"{first_name} {last_name}".strip()

        if not full_name:
            full_name = "Unknown Author"

        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
        }

    @staticmethod
    def validate_list_field(
        result: dict[str, Any],
        field_name: str,
        validator_func: Callable[[dict[str, Any] | None], dict[str, Any] | None],
    ) -> None:
        if field_name in result and isinstance(result[field_name], list):
            result[field_name] = [
                validated_item
                for item in result[field_name]
                if (validated_item := validator_func(item)) is not None
            ]

    @staticmethod
    def _validate_id_name_slug_dict(
        obj: dict[str, Any] | None, required_fields: list[str]
    ) -> dict[str, Any] | None:
        if not obj or not isinstance(obj, dict):
            return None

        obj_id = obj.get("id")
        name = obj.get("name")
        slug = obj.get("slug")

        if obj_id is None or name is None or slug is None:
            return None

        try:
            obj_id = int(obj_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(slug, str) or not slug.strip():
            return None

        return {"id": obj_id, "name": name.strip(), "slug": slug.strip()}

    @staticmethod
    def validate_grant_dict(grant: dict[str, Any]) -> dict[str, Any] | None:
        if not grant or not isinstance(grant, dict):
            return None

        SearchResultValidator._validate_grant_amount(grant)
        SearchResultValidator._validate_grant_created_by(grant)
        SearchResultValidator._validate_grant_contacts(grant)
        SearchResultValidator._validate_grant_applications(grant)

        return grant

    @staticmethod
    def _validate_grant_amount(grant: dict[str, Any]) -> None:
        if "amount" in grant and grant["amount"] is not None:
            if not isinstance(grant["amount"], dict):
                grant["amount"] = None

    @staticmethod
    def _validate_grant_created_by(grant: dict[str, Any]) -> None:
        if "created_by" not in grant:
            return
        created_by = grant["created_by"]
        if created_by is not None and not isinstance(created_by, dict):
            grant["created_by"] = None
        elif isinstance(created_by, dict):
            SearchResultValidator.validate_author_profile_in_dict(created_by)

    @staticmethod
    def _validate_grant_contacts(grant: dict[str, Any]) -> None:
        if "contacts" not in grant:
            return
        contacts = grant["contacts"]
        if contacts is None:
            grant["contacts"] = []
        elif isinstance(contacts, list):
            grant["contacts"] = SearchResultValidator._clean_contacts_list(contacts)
        else:
            grant["contacts"] = []

    @staticmethod
    def _validate_grant_applications(grant: dict[str, Any]) -> None:
        if "applications" not in grant:
            return
        applications = grant["applications"]
        if applications is None:
            grant["applications"] = []
        elif isinstance(applications, list):
            grant["applications"] = SearchResultValidator._clean_applications_list(
                applications
            )
        else:
            grant["applications"] = []

    @staticmethod
    def _clean_contacts_list(
        contacts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cleaned_contacts = []
        for contact in contacts:
            if isinstance(contact, dict):
                SearchResultValidator.validate_author_profile_in_dict(contact)
                cleaned_contacts.append(contact)
        return cleaned_contacts

    @staticmethod
    def _clean_applications_list(
        applications: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cleaned_applications = []
        for application in applications:
            if isinstance(application, dict):
                SearchResultValidator._validate_application_applicant(application)
                cleaned_applications.append(application)
        return cleaned_applications

    @staticmethod
    def _validate_application_applicant(application: dict[str, Any]) -> None:
        if "applicant" not in application:
            return
        applicant = application["applicant"]
        if (
            applicant is None
            or not isinstance(applicant, dict)
            or "id" not in applicant
        ):
            application["applicant"] = None

    @staticmethod
    def validate_author_profile_in_dict(obj: dict[str, Any]) -> None:
        if "author_profile" in obj:
            author_profile = obj["author_profile"]
            if author_profile is not None and not isinstance(author_profile, dict):
                obj["author_profile"] = None

    @staticmethod
    def validate_fundraise_dict(
        fundraise: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not fundraise or not isinstance(fundraise, dict):
            return None

        SearchResultValidator._validate_fundraise_amount_fields(fundraise)
        SearchResultValidator._validate_fundraise_created_by(fundraise)
        SearchResultValidator._validate_fundraise_contributors(fundraise)

        return fundraise

    @staticmethod
    def _validate_fundraise_amount_fields(fundraise: dict[str, Any]) -> None:
        for field in ["amount_raised", "goal_amount"]:
            if field in fundraise and fundraise[field] is not None:
                if not isinstance(fundraise[field], dict):
                    fundraise[field] = None

    @staticmethod
    def _validate_fundraise_created_by(fundraise: dict[str, Any]) -> None:
        if "created_by" not in fundraise:
            return
        created_by = fundraise["created_by"]
        if created_by is not None and not isinstance(created_by, dict):
            fundraise["created_by"] = None
        elif isinstance(created_by, dict):
            SearchResultValidator.validate_author_profile_in_dict(created_by)

    @staticmethod
    def _validate_fundraise_contributors(fundraise: dict[str, Any]) -> None:
        if "contributors" not in fundraise:
            return
        contributors = fundraise["contributors"]
        if contributors is None:
            fundraise["contributors"] = {"total": 0, "top": []}
        elif isinstance(contributors, dict):
            SearchResultValidator._validate_contributors_dict(contributors)
        else:
            fundraise["contributors"] = {"total": 0, "top": []}

    @staticmethod
    def _validate_contributors_dict(contributors: dict[str, Any]) -> None:
        SearchResultValidator._validate_contributors_total(contributors)
        SearchResultValidator._validate_contributors_top(contributors)

    @staticmethod
    def _validate_contributors_total(contributors: dict[str, Any]) -> None:
        if "total" in contributors:
            try:
                contributors["total"] = int(contributors["total"])
            except (ValueError, TypeError):
                contributors["total"] = 0

    @staticmethod
    def _validate_contributors_top(contributors: dict[str, Any]) -> None:
        if "top" not in contributors:
            return
        top = contributors["top"]
        if not isinstance(top, list):
            contributors["top"] = []
        else:
            contributors["top"] = SearchResultValidator._clean_contributors_top_list(
                top
            )

    @staticmethod
    def _clean_contributors_top_list(
        top: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cleaned_top = []
        for contributor in top:
            if isinstance(contributor, dict):
                SearchResultValidator.validate_author_profile_in_dict(contributor)
                cleaned_top.append(contributor)
        return cleaned_top

