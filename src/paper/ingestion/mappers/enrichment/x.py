"""
X (Twitter) data mapper for transforming API responses to XPost model format.

Maps X post data to ResearchHub XPost model fields.
"""

import logging
from typing import Any, Dict, List, Optional

from dateutil import parser as date_parser

from paper.related_models.x_post_model import XPost

logger = logging.getLogger(__name__)


class XMapper:
    """Maps X (Twitter) post data to XPost model instances."""

    def map_to_x_post(self, post_data: Dict[str, Any]) -> Optional[XPost]:
        """
        Map X API post data to XPost model instance.

        Args:
            post_data: Post data dict from X API response

        Returns:
            XPost model instance (not saved to database), or None if invalid
        """
        post_id = post_data.get("id")
        if not post_id:
            logger.warning("Post data missing required 'id' field")
            return None

        return XPost(
            post_id=post_id,
            author_id=post_data.get("author_id"),
            text=post_data.get("text", ""),
            posted_date=date_parser.parse(post_data["created_at"]),
            like_count=post_data.get("like_count", 0),
            repost_count=post_data.get("repost_count", 0),
            reply_count=post_data.get("reply_count", 0),
            quote_count=post_data.get("quote_count", 0),
            impression_count=post_data.get("impression_count", 0),
        )

    def map_to_x_posts(self, posts_data: List[Dict[str, Any]]) -> List[XPost]:
        """
        Map multiple X API post data dicts to XPost model instances.

        Args:
            posts_data: List of post data dicts from X API response

        Returns:
            List of XPost model instances (not saved to database)
        """
        x_posts = []
        for post_data in posts_data:
            x_post = self.map_to_x_post(post_data)
            if x_post:
                x_posts.append(x_post)
        return x_posts

    def extract_metrics(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract aggregated metrics from a list of posts.

        Args:
            posts: List of post dictionaries from X API

        Returns:
            Dictionary with aggregated metrics
        """
        if not posts:
            return {
                "post_count": 0,
                "total_likes": 0,
                "total_reposts": 0,
                "total_replies": 0,
                "total_quotes": 0,
                "total_impressions": 0,
            }

        total_likes = 0
        total_reposts = 0
        total_replies = 0
        total_quotes = 0
        total_impressions = 0

        for post in posts:
            total_likes += post.get("like_count", 0)
            total_reposts += post.get("repost_count", 0)
            total_replies += post.get("reply_count", 0)
            total_quotes += post.get("quote_count", 0)
            total_impressions += post.get("impression_count", 0)

        return {
            "post_count": len(posts),
            "total_likes": total_likes,
            "total_reposts": total_reposts,
            "total_replies": total_replies,
            "total_quotes": total_quotes,
            "total_impressions": total_impressions,
        }
