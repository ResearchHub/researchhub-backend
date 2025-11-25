FEED_CONFIG = {
    "following": {
        "use_cache": True,
        "allowed_sorts": ["hot_score_v2", "hot_score", "latest"],
    },
    "personalized": {
        "use_cache": False,
        "allowed_sorts": [],
    },
    "popular": {
        "allowed_sorts": ["aws_trending", "hot_score_v2", "hot_score"],
        # Per-ordering cache settings:
        # - aws_trending: No full-page cache (IDs cached in FeedService)
        # - hot_score_v2/hot_score: Full-page cache for DB sorts
        "cache_by_ordering": {
            "aws_trending": False,
            "hot_score_v2": True,
            "hot_score": True,
        },
    },
}

FEED_DEFAULTS = {
    "cache": {
        "num_pages_to_cache": 4,
    },
}
