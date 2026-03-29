from django.db import transaction

from research_ai.models import EmailTemplate


def list_templates():
    """Return all templates (shared for editors/moderators), ordered by updated_date descending."""
    return EmailTemplate.objects.select_related(
        "created_by",
        "created_by__author_profile",
    ).order_by("-updated_date")


def get_template(template_id):
    """
    Return the EmailTemplate with the given id, or None if not found.
    Shared: any editor/moderator can retrieve any template.
    template_id: int (or string that converts to int).
    """
    try:
        tid = int(template_id)
        return (
            EmailTemplate.objects.select_related(
                "created_by",
                "created_by__author_profile",
            )
            .filter(id=tid)
            .first()
        )
    except (ValueError, TypeError):
        return None


def create_template(user, **data):
    """
    Create a new EmailTemplate for the user.
    Returns the created instance.
    """
    allowed = {
        "name",
        "email_subject",
        "email_body",
    }
    kwargs = {}
    for k, v in data.items():
        if k not in allowed:
            continue
        kwargs[k] = v or ""
    kwargs["created_by"] = user
    return EmailTemplate.objects.create(**kwargs)


@transaction.atomic
def update_template(template_id, **data):
    """
    Update an EmailTemplate (shared: any editor/moderator can update).
    Returns (template, None) on success, (None, error_message) on not found.
    """
    template = get_template(template_id)
    if not template:
        return None, "Template not found."

    for key, value in data.items():
        if hasattr(template, key):
            setattr(template, key, value)
    template.save()
    return template, None


def delete_template(template_id):
    """
    Delete the EmailTemplate (shared: any editor/moderator can delete).
    Returns True if deleted, False if not found.
    """
    template = get_template(template_id)
    if not template:
        return False
    template.delete()
    return True
