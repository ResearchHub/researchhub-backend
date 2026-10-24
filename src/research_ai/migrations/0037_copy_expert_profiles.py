from django.db import migrations
from django.utils.dateparse import parse_datetime

# Frozen copies of the agent's markers, so later code changes cannot alter
# what this migration did.
NO_SUBMISSION_ERROR = "agent: did not submit a profile"
BATCH_SIZE = 500


def copy_expert_profiles(apps, schema_editor):
    """Copy each built ``Expert.profile`` into a ``ResearcherProfile`` row.

    The row is attached to the expert's ``registered_user`` when that user has
    no profile yet; the invitation and email matches are left to
    ``ResearcherProfileService``, which adopts these rows on first use.
    ``inputs_hash`` stays blank so the copy is not rebuilt just for lacking one.
    """
    Expert = apps.get_model("research_ai", "Expert")
    ResearcherProfile = apps.get_model("research_ai", "ResearcherProfile")

    claimed_user_ids = set(
        ResearcherProfile.objects.exclude(user=None).values_list("user_id", flat=True)
    )
    experts = (
        Expert.objects.exclude(profile={})
        .filter(researcher_profile__isnull=True)
        .order_by("id")
    )
    rows = []
    for expert in experts.iterator(chunk_size=BATCH_SIZE):
        data = expert.profile
        if not isinstance(data, dict) or not data:
            continue
        resolution = data.get("resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []

        user_id = expert.registered_user_id
        if user_id in claimed_user_ids:
            user_id = None
        elif user_id is not None:
            claimed_user_ids.add(user_id)

        if NO_SUBMISSION_ERROR in errors:
            status = "FAILED"
        elif resolution.get("openalex_author_id"):
            status = "READY"
        else:
            status = "UNRESOLVED"
        try:
            schema_version = int(data.get("schema_version") or 0)
        except TypeError, ValueError:
            schema_version = 0
        try:
            confidence = float(resolution.get("confidence"))
        except TypeError, ValueError:
            confidence = None

        rows.append(
            ResearcherProfile(
                user_id=user_id,
                expert_id=expert.id,
                status=status,
                schema_version=schema_version,
                openalex_author_id=str(resolution.get("openalex_author_id") or ""),
                orcid=str(resolution.get("orcid") or ""),
                confidence=confidence,
                data=data,
                built_at=parse_datetime(str(data.get("built_at") or "")),
                attempts=1 if status == "FAILED" else 0,
                last_error="; ".join(str(error) for error in errors)[:2000],
            )
        )
        if len(rows) >= BATCH_SIZE:
            ResearcherProfile.objects.bulk_create(rows)
            rows = []
    if rows:
        ResearcherProfile.objects.bulk_create(rows)


class Migration(migrations.Migration):
    dependencies = [
        ("research_ai", "0036_researcher_profile"),
    ]

    operations = [
        # Reversing drops nothing here: undoing 0036 drops the table, and
        # ``Expert.profile`` is left untouched by the copy.
        migrations.RunPython(copy_expert_profiles, migrations.RunPython.noop),
    ]
