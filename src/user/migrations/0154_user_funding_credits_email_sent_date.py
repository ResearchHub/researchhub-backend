from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0153_gatekeeper_research_ai_invited"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="funding_credits_email_sent_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
