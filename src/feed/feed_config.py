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
        "use_cache": True,
        "allowed_sorts": ["hot_score_v2", "hot_score"],
    },
}

FEED_DEFAULTS = {
    "cache": {
        "num_pages_to_cache": 4,
    },
}

PERSONALIZE_CONFIG = {
    "default_filter": "new-content",
    "num_results": 200,
    "cache_timeout": 1800,
}
