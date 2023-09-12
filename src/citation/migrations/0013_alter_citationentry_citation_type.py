from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("citation", "0012_citationproject_parent_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="citationentry",
            name="citation_type",
            field=models.CharField(
                choices=[
                    ("ARTWORK", "ARTWORK"),
                    ("AUDIO_RECORDING", "AUDIO_RECORDING"),
                    ("BILL", "BILL"),
                    ("BLOG_POST", "BLOG_POST"),
                    ("BOOK", "BOOK"),
                    ("BOOK_SECTION", "BOOK_SECTION"),
                    ("CASE", "CASE"),
                    ("CONFERENCE_PAPER", "CONFERENCE_PAPER"),
                    ("DICTIONARY_ENTRY", "DICTIONARY_ENTRY"),
                    ("DOCUMENT", "DOCUMENT"),
                    ("EMAIL", "EMAIL"),
                    ("ENCYCLOPEDIA_ARTICLE", "ENCYCLOPEDIA_ARTICLE"),
                    ("FILM", "FILM"),
                    ("FORUM_POST", "FORUM_POST"),
                    ("HEARING", "HEARING"),
                    ("INSTANT_MESSAGE", "INSTANT_MESSAGE"),
                    ("INTERVIEW", "INTERVIEW"),
                    ("JOURNAL_ARTICLE", "JOURNAL_ARTICLE"),
                    ("LETTER", "LETTER"),
                    ("MAGAZINE_ARTICLE", "MAGAZINE_ARTICLE"),
                    ("MANUSCRIPT", "MANUSCRIPT"),
                    ("MAP", "MAP"),
                    ("NEWSPAPER_ARTICLE", "NEWSPAPER_ARTICLE"),
                    ("PATENT", "PATENT"),
                    ("PODCAST", "PODCAST"),
                    ("PREPRINT", "PREPRINT"),
                    ("PRESENTATION", "PRESENTATION"),
                    ("RADIO_BROADCAST", "RADIO_BROADCAST"),
                    ("REPORT", "REPORT"),
                    ("SOFTWARE", "SOFTWARE"),
                    ("STATUTE", "STATUTE"),
                    ("THESIS", "THESIS"),
                    ("TV_BROADCAST", "TV_BROADCAST"),
                    ("VIDEO_RECORDING", "VIDEO_RECORDING"),
                    ("WEBPAGE", "WEBPAGE"),
                ],
                max_length=32,
            ),
        ),
    ]
