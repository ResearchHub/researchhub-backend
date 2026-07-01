from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("paper", "0173_paperversion_paper_ver_rh_doi_created_idx"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PaperSeriesDeclaration",
        ),
    ]
