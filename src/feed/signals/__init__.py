# Legacy signal imports - DISABLED
# The feed system now uses the generic feed manager in feed.feed_manager
# Signal handling is configured in feed.feed_configs.py

# Keep document_signals for unified document removal handling
from .document_signals import *  # noqa: F401, F403

# All other signals are now handled by the generic system
# from .bounty_signals import *  # noqa: F401, F403
# from .comment_signals import *  # noqa: F401, F403
# from .post_signals import *  # noqa: F401, F403
# from .purchase_signals import *  # noqa: F401, F403
# from .review_signals import *  # noqa: F401, F403
# from .vote_signals import *  # noqa: F401, F403
