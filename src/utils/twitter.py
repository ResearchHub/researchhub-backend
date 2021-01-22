import twitter
from researchhub.settings import (
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
    TWITER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
)

api = twitter.Api(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token_key=TWITER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
    tweet_mode='extended'
)


def get_twitter_results(query):
    results = api.GetSearch(
        term=query
    )
    return results


def get_twitter_url_results(url, filters=' -filter:retweets'):
    term = f'{url}'
    if filters:
        term += filters
    return get_twitter_results(term)


def get_twitter_doi_results(doi, filters=' -filter:retweets'):
    term = f'{doi}'
    if filters:
        term += filters
    return get_twitter_results(term)
