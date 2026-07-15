import django.db.models.deletion
from django.db import migrations, models


def resolve_duplicate_active_drafts(apps, schema_editor):
    proposal_draft = apps.get_model("research_ai", "ProposalDraft")
    active_statuses = ["PENDING", "PROCESSING"]
    duplicates = (
        proposal_draft.objects.filter(status__in=active_statuses)
        .values("search_expert_id")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
    )
    processing_first = models.Case(
        models.When(status="PROCESSING", then=models.Value(0)),
        default=models.Value(1),
        output_field=models.IntegerField(),
    )
    for duplicate in duplicates.iterator():
        drafts = proposal_draft.objects.filter(
            search_expert_id=duplicate["search_expert_id"],
            status__in=active_statuses,
        ).order_by(processing_first, "created_date", "id")
        keeper_id = drafts.values_list("id", flat=True).first()
        drafts.exclude(id=keeper_id).update(
            status="FAILED",
            error_message=(
                "Superseded while enforcing one active proposal draft per expert."
            ),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("invite", "0009_alter_invitation_recipient_email"),
        ("research_ai", "0017_generatedemail_complained_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedemail",
            name="note_invitation",
            field=models.ForeignKey(
                blank=True,
                db_comment="Invitation link embedded in proposal-draft outreach.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="generated_emails",
                to="invite.noteinvitation",
            ),
        ),
        migrations.AddField(
            model_name="generatedemail",
            name="outreach_context",
            field=models.JSONField(
                blank=True,
                db_comment=(
                    "Editor-provided proposal outreach fields used during generation."
                ),
                default=dict,
            ),
        ),
        migrations.AddField(
            model_name="generatedemail",
            name="proposal_draft",
            field=models.ForeignKey(
                blank=True,
                db_comment=(
                    "Expert-specific proposal draft referenced by this outreach email."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="generated_emails",
                to="research_ai.proposaldraft",
            ),
        ),
        migrations.AlterField(
            model_name="generatedemail",
            name="template",
            field=models.CharField(
                blank=True,
                choices=[
                    ("collaboration", "collaboration"),
                    ("consultation", "consultation"),
                    ("conference", "conference"),
                    ("peer-review", "peer-review"),
                    ("publication", "publication"),
                    ("rfp-outreach", "rfp-outreach"),
                    ("proposal-draft-outreach", "proposal-draft-outreach"),
                    ("custom", "custom"),
                ],
                db_comment=(
                    "LLM prompt key; null when placeholder is for fixed {{}} "
                    "template only."
                ),
                default="custom",
                max_length=32,
                null=True,
            ),
        ),
        migrations.RunPython(
            resolve_duplicate_active_drafts,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="proposaldraft",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=["PENDING", "PROCESSING"]),
                fields=("search_expert",),
                name="ra_pd_one_active_per_search_expert",
            ),
        ),
    ]
