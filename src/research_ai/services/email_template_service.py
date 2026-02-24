from django.db import transaction

from research_ai.models import EmailTemplate


def list_templates(user):
    """Return templates for the user, ordered by updated_date descending."""
    return EmailTemplate.objects.filter(created_by=user).order_by("-updated_date")


def get_template(user, template_id):
    """
    Return the EmailTemplate with the given id if it belongs to the user, else None.
    template_id: int (or string that converts to int).
    """
    try:
        tid = int(template_id)
        return EmailTemplate.objects.get(id=tid, created_by=user)
    except (ValueError, TypeError, EmailTemplate.DoesNotExist):
        return None


def create_template(user, **data):
    """
    Create a new EmailTemplate for the user. is_active defaults to False.
    Returns the created instance.
    """
    allowed = {
        "name",
        "contact_name",
        "contact_title",
        "contact_institution",
        "contact_email",
        "contact_phone",
        "contact_website",
        "outreach_context",
    }
    kwargs = {k: (v or "") for k, v in data.items() if k in allowed}
    kwargs["created_by"] = user
    kwargs["is_active"] = False
    return EmailTemplate.objects.create(**kwargs)


@transaction.atomic
def update_template(user, template_id, **data):
    """
    Update an EmailTemplate owned by the user. If is_active is True,
    deactivate all other templates for this user first.
    Returns (template, None) on success, (None, error_message) on not found.
    """
    template = get_template(user, template_id)
    if not template:
        return None, "Template not found."

    if data.get("is_active") is True:
        EmailTemplate.objects.filter(created_by=user).exclude(id=template.id).update(
            is_active=False
        )

    for key, value in data.items():
        if key != "created_by" and hasattr(template, key):
            setattr(template, key, value)
    template.save()
    return template, None


def delete_template(user, template_id):
    """
    Delete the EmailTemplate if it belongs to the user.
    Returns True if deleted, False if not found.
    """
    template = get_template(user, template_id)
    if not template:
        return False
    template.delete()
    return True
