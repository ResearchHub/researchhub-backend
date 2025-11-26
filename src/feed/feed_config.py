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
        "cache_by_ordering": {
            "aws_trending": False,
            "hot_score_v2": True,
            "hot_score": True,
        },
    },
    "latest": {
        "use_cache": True,
        "allowed_sorts": [],
    },
}

FEED_DEFAULTS = {
    "cache": {
        "num_pages_to_cache": 4,
    },
}
