import re


# Helpers for parsing and normalizing Digital Object Identifiers (DOIs).
class DOI:
    @staticmethod
    def normalize_doi(doi):
        """Convert DOI to standard https://doi.org/ format.
        Handles bare DOIs, doi.org URLs, and full https URLs.
        Returns None if input is invalid.
        """
        if not doi:
            return None

        # Convert to lowercase for case-insensitive comparison
        doi = doi.strip().rstrip("/").lower()

        # Handle various URL formats
        if "doi.org" in doi:
            # Extract everything after doi.org/
            parts = doi.split("doi.org/")
            if len(parts) < 2:
                return None
            # Remove any extra 'doi/' in the path
            bare_doi = parts[1].replace("doi/", "")
            return f"https://doi.org/{bare_doi}"

        # If it's a bare DOI (no domain), add the prefix
        return f"https://doi.org/{doi}"

    @staticmethod
    def get_bare_doi(doi):
        """Extract bare DOI from any DOI format.
        Args:
            doi: Any DOI format (bare, with domain, or full URL)
        Returns:
            Bare DOI (e.g. "10.1111/ijsw.12716") or None if invalid
        """
        normalized = DOI.normalize_doi(doi)
        if not normalized:
            return None

        # Extract bare DOI from normalized version
        return normalized.split("doi.org/")[-1]

    @staticmethod
    def is_doi(text):
        """
        Checks if a string matches DOI pattern
        """
        if not text or not isinstance(text, str):
            return False

        # Remove common DOI URL prefixes
        cleaned_text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)

        # Simpler DOI pattern that matches 10.XXXX/any.characters
        doi_regex = r"10\.\d{4,}/[-._;()\/:a-zA-Z0-9]+"
        match = re.search(doi_regex, cleaned_text)

        return bool(match)
