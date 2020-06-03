import twitter
import time
import datetime

from django.core.management.base import BaseCommand

from paper.models import Paper
from discussion.models import Thread, Comment
from researchhub.settings import (
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
    TWITER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
)

SOURCE = 'twitter'


class Command(BaseCommand):

    def __init__(self, *args, **kwargs):
        self.api = twitter.Api(
            consumer_key=TWITTER_CONSUMER_KEY,
            consumer_secret=TWITTER_CONSUMER_SECRET,
            access_token_key=TWITER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
            tweet_mode='extended'
        )

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            doi__isnull=False,
            url__isnull=False,
        )
        papers = papers.exclude(
            doi__iexact='',
            url__iexact='',
        )
        paper_iterator = papers.iterator()
        paper_count = papers.count()
        count = 0

        paper = next(paper_iterator)
        while count < paper_count:
            url = paper.url
            print(f'{count}/{paper_count}')
            print(f'Searching tweets for {url}')
            try:
                results = self.api.GetSearch(
                    term=f'{url} -filter:retweets'
                )
                for res in results:
                    source_id = res.id_str
                    username = res.user.screen_name
                    thread_user_profile_img = res.user.profile_image_url_https
                    thread_created_date = res.created_at_in_seconds
                    thread_created_date = datetime.datetime.fromtimestamp(
                        thread_created_date,
                        datetime.timezone.utc
                    )
                    text = res.full_text

                    external_thread_metadata = {
                        'source_id': source_id,
                        'username': username,
                        'picture': thread_user_profile_img,
                        'url': f'https://twitter.com/{username}/status/{source_id}'
                    }
                    thread = Thread.objects.create(
                        paper=paper,
                        source=SOURCE,
                        external_metadata=external_thread_metadata,
                        plain_text=text,
                    )
                    thread.created_date = thread_created_date
                    thread.save()

                    replies = self.api.GetSearch(
                        term=f'to:{username}'
                    )
                    for reply in replies:
                        reply_username = reply.user.screen_name
                        reply_id = reply.id_str
                        reply_text = reply.full_text
                        thread_user_profile_img = reply.user.profile_image_url_https
                        comment_created_date = reply.created_at_in_seconds
                        comment_created_date = datetime.datetime.fromtimestamp(
                            comment_created_date,
                            datetime.timezone.utc
                        )

                        external_comment_metadata = {
                            'source_id': reply_id,
                            'username': reply_username,
                            'picture': thread_user_profile_img,
                            'url': f'https://twitter.com/{reply_username}/status/{reply_id}'
                        }
                        comment = Comment.objects.create(
                            parent=thread,
                            source=SOURCE,
                            external_metadata=external_comment_metadata,
                            plain_text=reply_text,
                        )
                        comment.created_date = comment_created_date
                        comment.save()

                count += 1
                paper = next(paper_iterator)
                time.sleep(10)
            except Exception as e:
                print(e)
                print('Rate limiting')
                time.sleep(60)
