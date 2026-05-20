from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("risk_score", "0001_initial"),
        ("user", "0144_riskscore_transfer"),
    ]

    state_operations = [
        migrations.DeleteModel(name="RiskScore"),
        migrations.DeleteModel(name="RiskScoreEvent"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=state_operations),
    ]
