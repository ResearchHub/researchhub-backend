import twitter
import time
import datetime

from django.core.management.base import BaseCommand

from paper.models import Paper
from discussion.models import Thread, Comment

consumer_key = 'l1asT7ZKpn8CWj9heB54yq7nX'
consumer_secret = 'qymqOrtuwGvVqcbywyVW2842DQKfwOTRGkBGmNHf9UT87owGQH'
access_token_key = '1234900010782740482-BXPIhwT4Bo8gsphzbWdgmdbrF0wXYL'
access_token_secret = 'k5rOGKNkM5KvewADTfjfUbi6VJg2ws2VBxdiuHURCHLaQ'
SOURCE = 'twitter'


class Command(BaseCommand):

    def __init__(self, *args, **kwargs):
        self.api = twitter.Api(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token_key=access_token_key,
            access_token_secret=access_token_secret,
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
                        'picture': thread_user_profile_img
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
                            'picture': thread_user_profile_img
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
