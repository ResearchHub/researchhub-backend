"""
Seed a mix of user-generated content (papers, posts, comments) so the local
`/api/feed/user_generated/` endpoint has something to return. Intended for
local development only; not safe to run in production.

Usage:
    cd src && uv run python manage.py seed_user_generated_feed
    cd src && uv run python manage.py seed_user_generated_feed --count 6
    cd src && uv run python manage.py seed_user_generated_feed --clean
"""

import random
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from hub.models import Hub
from paper.models import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

SEED_TAG = "[SEED]"
# A signal in this codebase overwrites `username` with `email`, so we
# identify seeded users by this email suffix instead of a username prefix.
SEED_EMAIL_DOMAIN = "@seed.local"
SEED_HUB_SLUG = "seed-test-hub"

# (first_name, last_name, email)
SEED_USERS = [
    ("Ada", "Researcher", f"ada{SEED_EMAIL_DOMAIN}"),
    ("Ben", "Grad", f"ben{SEED_EMAIL_DOMAIN}"),
    ("Carl", "Sloppy", f"carl{SEED_EMAIL_DOMAIN}"),
    ("Dave", "Spam", f"dave{SEED_EMAIL_DOMAIN}"),
]

HIGH_QUALITY_PAPERS = [
    {
        "title": "Sparse autoencoders for interpretable feature decomposition in LLMs",
        "abstract": (
            "We train sparse autoencoders on the residual stream of a 7B "
            "parameter language model and recover ~16k monosemantic features "
            "across math, code, and natural-language domains."
        ),
    },
    {
        "title": (
            "Catalytic asymmetric synthesis of beta-lactams via Cu(I) "
            "carbene transfer"
        ),
        "abstract": (
            "A new chiral N-heterocyclic carbene ligand enables the catalytic "
            "asymmetric synthesis of beta-lactams in 92-99% ee."
        ),
    },
    {
        "title": (
            "Phase II trial of low-dose naltrexone for fibromyalgia "
            "symptom reduction"
        ),
        "abstract": (
            "Randomized, placebo-controlled trial (n=147) showing 38% "
            "reduction in pain VAS scores after 12 weeks."
        ),
    },
]

LOW_QUALITY_PAPERS = [
    {
        "title": "MY AMAZING DISCOVERY THAT WILL CHANGE EVERYTHING!!!",
        "abstract": "trust me bro this is huge. read the paper.",
    },
    {
        "title": "asdfasdf test paper please ignore",
        "abstract": "lorem ipsum dolor sit amet",
    },
    {
        "title": "Buy cheap watches at superdeals dot com",
        "abstract": "Click here for amazing deals on luxury replicas!!!",
    },
]

HIGH_QUALITY_POSTS = [
    {
        "document_type": "DISCUSSION",
        "title": "Reproducing the Anthropic SAE results on Llama-3 8B",
        "renderable_text": (
            "I've been trying to reproduce the dictionary learning results "
            "from the recent Anthropic paper on Llama-3 8B. Sharing my "
            "training config, observed feature density, and questions about "
            "the optimal L1 coefficient for this scale."
        ),
    },
    {
        "document_type": "QUESTION",
        "title": "Best practices for handling left-censored mass spec data?",
        "renderable_text": (
            "Working on a metabolomics dataset with ~30% values below LOQ. "
            "Curious whether folks here prefer multiple imputation, MNAR "
            "modeling, or just hard thresholding for downstream PCA."
        ),
    },
    {
        "document_type": "DISCUSSION",
        "title": "Open data release: 50k annotated electron microscopy images",
        "renderable_text": (
            "Releasing under CC-BY a dataset of 50,000 electron microscopy "
            "images of synaptic vesicles, each labeled by two trained "
            "annotators. Looking for collaborators on benchmark tasks."
        ),
    },
]

LOW_QUALITY_POSTS = [
    {
        "document_type": "DISCUSSION",
        "title": "first post check",
        "renderable_text": "test test test",
    },
    {
        "document_type": "QUESTION",
        "title": "DOES ANYONE KNOW HOW TO DO SCIENCE",
        "renderable_text": "im new here please help i need to publish",
    },
    {
        "document_type": "DISCUSSION",
        "title": "FREE RSC GIVEAWAY click my profile",
        "renderable_text": "send me 10 RSC and i send back 100, trust",
    },
]

HIGH_QUALITY_COMMENTS = [
    "Thanks for sharing the training config. Did you try varying the L1 "
    "coefficient between 1e-4 and 5e-3? In our runs, the lower end gave "
    "noticeably more polysemantic features.",
    "I appreciate the open data release. One concern: were the two "
    "annotators blinded to each other's labels? The reported IAA is "
    "high enough that I want to make sure it's not from convergence.",
    "Have you considered MNAR with a quantile-based threshold? We've had "
    "good luck combining it with rank-based normalization for downstream "
    "PCA on similar data sizes.",
]

LOW_QUALITY_COMMENTS = [
    "first",
    "this is wrong but i wont say why",
    "DM ME FOR THE REAL ANSWER!!! 1!11",
    "lol ok",
]


class Command(BaseCommand):
    help = (
        "Seed user-generated content (papers, posts, comments) for local "
        "testing of /api/feed/user_generated/. NOT for production use."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=4,
            help=(
                "Number of items per type to create. Quality is mixed "
                "roughly 50/50."
            ),
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            default=False,
            help=(
                "Delete all previously-seeded content "
                "(anything owned by users with @seed.local emails)."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not getattr(settings, "TESTING", False):
            self.stderr.write(
                self.style.ERROR(
                    "Refusing to run outside DEBUG/TESTING. This command "
                    "creates fake content and is for local use only."
                )
            )
            return

        if options["clean"]:
            self._clean()
            return

        self._seed(count=options["count"])

    def _seed(self, count):
        users = self._get_or_create_seed_users()
        hub = self._get_or_create_seed_hub()

        papers = self._seed_papers(users, hub, count=count)
        posts = self._seed_posts(users, hub, count=count)
        self._seed_comments(users, papers, posts, count=count)

        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(
            "Hit GET /api/feed/user_generated/ as a moderator to view "
            "the seeded entries."
        )

    def _get_or_create_seed_users(self):
        users = []
        for first, last, email in SEED_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email,
                    "first_name": first,
                    "last_name": last,
                },
            )
            users.append(user)
            self.stdout.write(
                f"{'Created' if created else 'Reusing'} user {email} (id={user.id})"
            )
        return users

    def _get_or_create_seed_hub(self):
        hub, created = Hub.objects.get_or_create(
            slug=SEED_HUB_SLUG,
            defaults={"name": "Seed Test Hub"},
        )
        self.stdout.write(
            f"{'Created' if created else 'Reusing'} hub {hub.slug} (id={hub.id})"
        )
        return hub

    def _seed_papers(self, users, hub, count):
        paper_ct = ContentType.objects.get_for_model(Paper)
        now = timezone.now()
        papers = []

        templates = self._mix(HIGH_QUALITY_PAPERS, LOW_QUALITY_PAPERS, count)
        for i, tpl in enumerate(templates):
            user = users[i % len(users)]
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            )
            paper = Paper.objects.create(
                title=f"{SEED_TAG} {tpl['title']}",
                paper_title=f"{SEED_TAG} {tpl['title']}",
                paper_publish_date=now - timedelta(days=i),
                abstract=tpl["abstract"],
                uploaded_by=user,
                unified_document=unified_doc,
            )
            unified_doc.hubs.add(hub)

            create_feed_entry(
                item_id=paper.id,
                item_content_type_id=paper_ct.id,
                action=FeedEntry.PUBLISH,
                hub_ids=[hub.id],
                user_id=user.id,
            )
            papers.append(paper)
            self.stdout.write(
                f"  paper id={paper.id} by {user.username}: {tpl['title'][:60]}"
            )

        return papers

    def _seed_posts(self, users, hub, count):
        post_ct_model_id = None
        now = timezone.now()
        posts = []

        templates = self._mix(HIGH_QUALITY_POSTS, LOW_QUALITY_POSTS, count)
        for i, tpl in enumerate(templates):
            user = users[i % len(users)]
            post = create_post(
                title=f"{SEED_TAG} {tpl['title']}",
                renderable_text=tpl["renderable_text"],
                created_by=user,
                document_type=tpl["document_type"],
            )
            post.unified_document.hubs.add(hub)

            if post_ct_model_id is None:
                post_ct_model_id = ContentType.objects.get_for_model(post).id

            create_feed_entry(
                item_id=post.id,
                item_content_type_id=post_ct_model_id,
                action=FeedEntry.PUBLISH,
                hub_ids=[hub.id],
                user_id=user.id,
            )
            # Stagger action_date so listings show ordering.
            FeedEntry.objects.filter(
                content_type_id=post_ct_model_id, object_id=post.id
            ).update(action_date=now - timedelta(hours=i))
            posts.append(post)
            self.stdout.write(
                f"  post  id={post.id} by {user.username}: {tpl['title'][:60]}"
            )

        return posts

    def _seed_comments(self, users, papers, posts, count):
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        post_ct = ContentType.objects.get_for_model(posts[0]) if posts else None
        paper_ct = ContentType.objects.get_for_model(Paper) if papers else None

        targets = []
        if posts:
            targets.extend([(p, post_ct) for p in posts])
        if papers:
            targets.extend([(p, paper_ct) for p in papers])

        if not targets:
            self.stdout.write("No paper/post targets available for comments.")
            return

        comments_text = self._mix(HIGH_QUALITY_COMMENTS, LOW_QUALITY_COMMENTS, count)
        for i, text in enumerate(comments_text):
            user = users[i % len(users)]
            target, target_ct = targets[i % len(targets)]

            thread = RhCommentThreadModel.objects.create(
                content_type=target_ct,
                object_id=target.id,
                created_by=user,
                updated_by=user,
            )
            comment = RhCommentModel.objects.create(
                thread=thread,
                created_by=user,
                updated_by=user,
                comment_content_json={"ops": [{"insert": f"{text}\n"}]},
                context_title=f"{SEED_TAG} comment",
            )

            create_feed_entry(
                item_id=comment.id,
                item_content_type_id=comment_ct.id,
                action=FeedEntry.PUBLISH,
                hub_ids=[],
                user_id=user.id,
            )
            self.stdout.write(
                f"  comment id={comment.id} by {user.username} on "
                f"{target_ct.model} {target.id}: {text[:50]}"
            )

    def _mix(self, high_quality, low_quality, count):
        """Return `count` templates with a roughly even quality split."""
        rng = random.Random(42)
        pool = []
        n_high = (count + 1) // 2
        n_low = count - n_high
        for i in range(n_high):
            pool.append(high_quality[i % len(high_quality)])
        for i in range(n_low):
            pool.append(low_quality[i % len(low_quality)])
        rng.shuffle(pool)
        return pool

    def _clean(self):
        seed_users = list(User.objects.filter(email__endswith=SEED_EMAIL_DOMAIN))
        if not seed_users:
            self.stdout.write("No seed users found; nothing to clean.")
            return

        user_ids = [u.id for u in seed_users]
        self.stdout.write(f"Cleaning content for {len(user_ids)} seed users...")

        # SoftDeletable models override `objects.delete()` to soft-delete and
        # return None. We want a hard delete of seed data, so route through
        # `all_objects` (vanilla Manager) where available.
        feed_count = self._hard_delete(FeedEntry.objects.filter(user_id__in=user_ids))
        comment_count = self._hard_delete(
            RhCommentModel.all_objects.filter(created_by_id__in=user_ids)
        )
        thread_count = self._hard_delete(
            RhCommentThreadModel.objects.filter(created_by_id__in=user_ids)
        )

        post_unified_ids = list(
            ResearchhubUnifiedDocument.all_objects.filter(
                posts__created_by_id__in=user_ids
            ).values_list("id", flat=True)
        )
        paper_unified_ids = list(
            ResearchhubUnifiedDocument.all_objects.filter(
                paper__uploaded_by_id__in=user_ids
            ).values_list("id", flat=True)
        )
        unified_ids = list(set(post_unified_ids + paper_unified_ids))

        # Cascade through unified documents (deletes Paper/Post via FK).
        unified_count = self._hard_delete(
            ResearchhubUnifiedDocument.all_objects.filter(id__in=unified_ids)
        )

        user_count = self._hard_delete(User.objects.filter(id__in=user_ids))

        # Drop the seed hub if empty.
        hub_qs = Hub.objects.filter(slug=SEED_HUB_SLUG)
        hub_count = 0
        for hub in hub_qs:
            if not hub.related_documents.exists():
                hub.delete()
                hub_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Cleaned: feed_entries={feed_count}, comments={comment_count}, "
                f"threads={thread_count}, unified_documents={unified_count}, "
                f"users={user_count}, hubs={hub_count}"
            )
        )

    def _hard_delete(self, queryset):
        """Hard-delete a queryset and return the row count, regardless of
        whether the manager is vanilla or soft-deletable."""
        result = queryset.delete()
        if isinstance(result, tuple):
            return result[0]
        return None
