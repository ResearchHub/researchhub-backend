import twitter
import time

from django.core.management.base import BaseCommand

from paper.models import Paper
from discussion.models import ExternalThread, ExternalComment

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
            doi = paper.doi
            url = paper.url
            print(f'Searching tweets for {url}')
            try:
                results = self.api.GetSearch(
                    term=f'{url} -filter:retweets'
                )
                for res in results:
                    source_id = res.id_str
                    username = res.user.screen_name
                    user_profile_img = res.user.profile_image_url_https
                    text = res.full_text
                    thread = ExternalThread.objects.create(
                        paper=paper,
                        source_id=source_id,
                        source=SOURCE,
                        username=username,
                        plain_text=text,
                    )
                    replies = self.api.GetSearch(
                        term=f'to:{username}'
                    )
                    for reply in replies:
                        reply_username = reply.user.screen_name
                        reply_id = reply.id_str
                        reply_text = reply.full_text
                        ExternalComment.objects.create(
                            parent=thread,
                            source_id=reply_id,
                            source=SOURCE,
                            username=reply_username,
                            plain_text=reply_text
                        )
                count += 1
                paper = next(paper_iterator)
                time.sleep(10)
            except Exception as e:
                print(e)
                print('Rate limiting')
                time.sleep(60)



    # New discussion models for external sources?
    # class ExternalThread:
        # source = models.CharField
        # id = models.CharField
        # username = models.CharField
        # other info?