RH_COMMENT_FIELDS = [
    "comment_content_markdown",
    "comment_content_type",
    "context_title",
    "parent_id",  # expose only the id. No need to display entire instance
    "responses",
    "thread_id",
]
RH_COMMENT_READ_ONLY_FIELDS = [
    "comment_content_markdown",
    "parent_id",  # expose only the id. No need to display entire instance
    "responses",
    "thread_id",
]
