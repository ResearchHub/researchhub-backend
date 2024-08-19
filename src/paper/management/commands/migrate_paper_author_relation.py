from django.core.management.base import BaseCommand
from django.db import transaction

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper


class Command(BaseCommand):
    """
    This command is used to migrate the relation between papers and authors
    from the previous paper_paper_author table to the new paper_authorship table.

    This is a one-time command that should be run only once to migrate the data.
    """

    def handle(self, *args, **options):
        created = 0
        exited = 0
        paper_count = 0

        for paper in (
            Paper.objects.filter(authors__isnull=False)
            .only("authors")
            .distinct()
            .iterator(chunk_size=1000)
        ):
            paper_count += 1
            print(f"* {paper_count}. Paper: {paper.id}")
            for author in paper.authors.iterator():
                with transaction.atomic():
                    print(f"   paper {paper.id}:author {author.id}", end="")
                    if Authorship.objects.filter(
                        paper_id=paper.id, author=author
                    ).exists():
                        print(" -> already exists")
                        exited += 1
                        continue
                    else:
                        pos, corresponding = self.get_position_corresponding(
                            paper.raw_authors, author
                        )
                        print(
                            f" -> creating with pos: {pos}, corresponding: {corresponding})"
                        )
                        Authorship.objects.create(
                            paper=paper,
                            author=author,
                            author_position=pos,
                            is_corresponding=corresponding,
                            source="AUTHOR_MIGRATION",
                        )
                        created += 1

        print(
            f"Total papers: {paper_count}; authorships => existed: {exited}, created: {created}"
        )

    def get_position_corresponding(self, raw_authors, author):
        pos = "middle"
        corresponding = False
        try:
            if (
                raw_authors is not None
                and len(raw_authors) > 0
                and isinstance(raw_authors, list)
            ):
                first_raw_author = self.get_fullname(raw_authors[0])
                last_raw_author = self.get_fullname(raw_authors[-1])
                if author.full_name.lower() == first_raw_author.lower():
                    pos = "first"
                elif (
                    author.full_name.lower() == last_raw_author.lower()
                    and len(raw_authors) > 1
                ):
                    pos = "last"
                for raw_author in raw_authors:
                    current_raw_author = self.get_fullname(raw_author)
                    if (
                        author.full_name.lower() == current_raw_author.lower()
                        and raw_author.get("is_corresponding")
                    ):
                        corresponding = True
                        break
        except Exception as e:
            print(f" -> Error: {e}")
        return pos, corresponding

    def get_fullname(self, raw_author):
        return f"{raw_author.get('first_name', '')} {raw_author.get('last_name', '')}"
