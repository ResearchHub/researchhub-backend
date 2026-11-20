import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authtoken", "0004_alter_tokenproxy_options"),
        ("user", "0154_user_complete_profile_email_sent_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthTokenActivity",
            fields=[
                (
                    "token",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="activity",
                        serialize=False,
                        to="authtoken.token",
                    ),
                ),
                ("issued_at", models.DateTimeField()),
                ("last_used_at", models.DateTimeField()),
            ],
        ),
        migrations.RunSQL(
            sql="""
                INSERT INTO user_authtokenactivity (token_id, issued_at, last_used_at)
                SELECT key, now(), now() FROM authtoken_token
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
