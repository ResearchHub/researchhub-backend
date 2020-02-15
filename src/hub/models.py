from django.db import models
from django.db.models import Q, Count

from paper.models import Vote as PaperVote


class Hub(models.Model):
    UNLOCK_AFTER = 14

    name = models.CharField(max_length=1024, unique=True)
    acronym = models.CharField(max_length=255, default='', blank=True)
    is_locked = models.BooleanField(default=False)
    subscribers = models.ManyToManyField(
        'user.User',
        related_name='subscribed_hubs'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}, locked: {}'.format(self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        return super(Hub, self).save(*args, **kwargs)

    @property
    def subscriber_count_indexing(self):
        return len(self.subscribers.all())

    def email_context(self, start_date, end_date):

        upvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=PaperVote.UPVOTE,
                vote__updated_date__gte=start_date,
                vote__updated_date__lte=end_date
            )
        )

        downvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=PaperVote.DOWNVOTE,
                vote__created_date__gte=start_date,
                vote__created_date__lte=end_date
            )
        )

        thread_counts = Count(
            'threads',
            filter=Q(
                threads__created_date__gte=start_date,
                threads__created_date__lte=end_date,
            )
        )

        comment_counts = Count(
            'threads__comments',
            filter=Q(
                threads__comments__created_date__gte=start_date,
                threads__comments__created_date__lte=end_date,
            )
        )

        reply_counts = Count(
            'threads__comments__replies',
            filter=Q(
                threads__comments__replies__created_date__gte=start_date,
                threads__comments__replies__created_date__lte=end_date,
            )
        )

        papers = []
        # Most Voted uploaded in Interval
        paper = self.papers.filter(uploaded_date__gte=start_date, uploaded_date__lte=end_date).annotate(score=upvotes - downvotes).order_by('-score').first()
        if paper:
            papers.append(paper)

        # Most Discussed
        # TODO grab second if neccesary?
        paper = self.papers.annotate(discussion_count=thread_counts + comment_counts + reply_counts).order_by('-discussion_count').first()
        if paper and paper not in papers:
            papers.append(paper)

        # Most Voted in Interval
        # TODO grab second if necessary
        paper = self.papers.annotate(score=upvotes - downvotes).filter(score__gt=0).order_by('-score').first()
        if paper and paper not in papers:
            papers.append(paper)
        return papers

    def unlock(self):
        self.is_locked = False
        self.save()
