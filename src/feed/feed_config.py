FEED_CONFIG = {
    "following": {
        "use_cache": True,
        "allowed_sorts": ["hot_score_v2", "hot_score", "latest"],
    },
    "popular": {
        "use_cache": True,
        "allowed_sorts": ["hot_score_v2", "hot_score"],
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
