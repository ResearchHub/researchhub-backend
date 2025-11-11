FEED_CONFIG = {
    "following": {
        "use_cache": True,
        "supports_diversification": True,
        "allowed_sorts": ["hot_score_v2", "hot_score", "latest"],
    },
    "personalized": {
        "use_cache": True,
        "supports_diversification": False,
        "allowed_sorts": [],
    },
    "popular": {
        "use_cache": True,
        "supports_diversification": False,
        "allowed_sorts": ["hot_score_v2", "hot_score"],
    },
}

FEED_DEFAULTS = {
    "cache": {
        "num_pages_to_cache": 4,
    },
    "diversification": {
        "max_consecutive": 2,
        "reinject_interval": 5,
        "num_pages_to_diversify": 4,
        "grouping_field": "subcategory",
    },
}
