"""
Utilities for preventing circular dependencies in comment serializers.
"""

DEFAULT_MAX_DEPTH = 2


def get_serialization_depth(context):
    """Get the current serialization depth from context."""
    return context.get("serialization_depth", 0)


def increment_depth(context):
    """Return a new context with incremented depth."""
    new_context = context.copy()
    new_context["serialization_depth"] = get_serialization_depth(context) + 1
    return new_context


def should_use_reference_only(context, max_depth=DEFAULT_MAX_DEPTH):
    """Check if we should use reference-only serialization due to depth limits."""
    return get_serialization_depth(context) >= max_depth


def create_thread_reference(thread):
    """Create a reference-only representation of a thread."""
    return {
        "id": thread.id,
        "thread_type": thread.thread_type,
        "anchor": thread.anchor,
        "created_date": thread.created_date,
        "updated_date": thread.updated_date,
    }


def create_comment_reference(comment):
    """Create a reference-only representation of a comment."""
    return {
        "id": comment.id,
        "created_date": comment.created_date,
        "updated_date": comment.updated_date,
        "created_by": comment.created_by_id,
    }


def create_content_object_reference(content_object):
    """Create a reference-only representation of a content object."""
    return {
        "id": content_object.id,
        "name": content_object._meta.model_name,
        "title": getattr(content_object, "title", None),
        "created_date": getattr(content_object, "created_date", None),
    }
