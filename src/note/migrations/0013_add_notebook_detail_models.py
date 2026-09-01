import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("note", "0012_add_note_draft_columns"),
        ("organizations", "0001_initial"),
        ("user", "0150_author_user_soft_delete_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="NoteAuthor",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.IntegerField()),
                (
                    "note",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="author_links",
                        to="note.note",
                    ),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="user.author",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "id"],
                "unique_together": {("note", "author")},
            },
        ),
        migrations.AddField(
            model_name="note",
            name="authors",
            field=models.ManyToManyField(
                related_name="authored_notes",
                through="note.NoteAuthor",
                to="user.author",
            ),
        ),
        migrations.CreateModel(
            name="GrantSettings",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "amount",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=19,
                        null=True,
                    ),
                ),
                (
                    "currency",
                    models.CharField(blank=True, max_length=16),
                ),
                (
                    "organization",
                    models.CharField(blank=True, max_length=255),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "end_date",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "application_visibility",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("OPTIONAL", "Applicant chooses"),
                            ("PRIVATE", "Applications must be private"),
                            ("PUBLIC", "Applications must be public"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "note",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grant_settings",
                        to="note.note",
                    ),
                ),
                (
                    "contacts",
                    models.ManyToManyField(
                        blank=True,
                        related_name="note_grant_settings_contacts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "note_grant_settings",
            },
        ),
        migrations.CreateModel(
            name="PreregistrationSettings",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "goal_amount",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=19,
                        null=True,
                    ),
                ),
                (
                    "goal_currency",
                    models.CharField(blank=True, max_length=16),
                ),
                (
                    "duration_days",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "is_public",
                    models.BooleanField(blank=True, null=True),
                ),
                (
                    "note",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preregistration_settings",
                        to="note.note",
                    ),
                ),
                (
                    "nonprofit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="note_preregistration_settings",
                        to="organizations.nonprofitorg",
                    ),
                ),
            ],
            options={
                "db_table": "note_preregistration_settings",
            },
        ),
    ]
