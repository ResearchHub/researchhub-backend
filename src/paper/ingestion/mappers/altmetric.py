from datetime import datetime, timezone
from typing import Any, Dict


class AltmetricMapper:
    def map_metrics(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map Altmetric API response to internal representation.

        Args:
            record: Raw Altmetric data as returned by the Altmetric API

        Returns:
            Mapped dictionary with selected Altmetric fields
        """
        if not record:
            return {}

        last_updated_raw = record.get("last_updated", 0)
        last_updated = None
        if last_updated_raw:
            try:
                # Convert to float in case it's a string
                timestamp = float(last_updated_raw)
                last_updated = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (ValueError, TypeError):
                # If conversion fails, leave as None
                last_updated = None

        mapped = {
            "altmetric_id": record.get("altmetric_id", None),
            "facebook_count": record.get("cited_by_fbwalls_count", 0),
            "twitter_count": record.get("cited_by_tweeters_count", 0),
            "bluesky_count": record.get("cited_by_bluesky_count", 0),
            "score": record.get("score", 0.0),
            "last_updated": last_updated,
        }

        return mapped
