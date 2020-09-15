import json
import sift.client

from ipware import get_client_ip

from researchhub.settings import SIFT_ACCOUNT_ID, SIFT_REST_API_KEY
from utils import sentry

# https://sift.com/resources/guides/content-abuse

client = sift.Client(api_key=SIFT_REST_API_KEY, account_id=SIFT_ACCOUNT_ID)


def get_user_score(user_id):
    try:
        response = client.score(user_id)
        out = json.dumps(response.body)
        print(out)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


def label_bad_user(user_id, abuse_type, description=''):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.label(user_id, {
            '$is_bad': True,
            # optional fields
            '$abuse_type': abuse_type,
            '$description': description,
            '$source': 'django',
            '$analyst': 'dev@quantfive.org'
        })
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


def unlabel_user(user_id):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.unlabel(user_id, abuse_type='content_abuse')
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


class EventsApi:

    def create_meta_properties(self, properties, request, exclude_ip=False):
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        properties['$browser'] = {
            '$user_agent': user_agent
        }

        if not exclude_ip:
            ip, is_routable = get_client_ip(request)
            if ip:
                properties['ip'] = ip

    def track_account(self, user, request, update=False):
        properties = {
            # Required Fields
            '$user_id': str(user.id),

            # Supported Fields
            '$user_email': user.email,
            '$name': f'{user.first_name} {user.last_name}',
            '$social_sign_on_type': '$google',
        }
        self.create_meta_properties(properties, request, exclude_ip=True)
        track_type = '$update_account' if update else '$create_account'

        try:
            response = client.track(track_type, properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_login(self, user, login_status, request):
        # https://sift.com/developers/docs/python/events-api/reserved-events/login
        properties = {
            '$user_id': str(user.id),
            '$login_status': login_status,

            '$username': user.username,
        }
        self.create_meta_properties(properties, request)

        try:
            response = client.track('$login', properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_comment(
        self,
        user,
        comment,
        request,
        is_thread=False,
        update=False
    ):
        root_content_id = ''
        if comment.paper is not None:
            root_content_id = (
                f'{type(comment.paper).__name__}_{comment.paper.id}'
            )

        comment_properties = {
            # Required fields
            '$user_id': str(user.id),
            # must be unique across all content types
            '$content_id': f'{type(comment).__name__}_{comment.id}',

            # Recommended fields
            '$status': '$active',

            # Required $comment object
            '$comment': {
                '$body': comment.plain_text,
                '$contact_email': user.email,
                '$root_content_id': root_content_id,
            }
        }
        if not is_thread:
            comment_properties['$comment']['$parent_comment_id'] = (
                f'{type(comment.parent).__name__}_{comment.parent.id}'
            )

        self.create_meta_properties(comment_properties, request)
        track_type = '$update_content' if update else '$create_content'

        try:
            response = client.track(track_type, comment_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_paper(self, user, paper, request, update=False):
        post_properties = {
            # Required fields
            '$user_id': str(user.id),
            '$content_id': f'{type(paper).__name__}_{paper.id}',

            # Recommended fields
            '$status': '$active',

            # Required $post object
            '$post': {
                '$subject': paper.title,
                '$body': paper.paper_title,
                '$contact_email': user.email,
                '$contact_address': {
                    '$name': f'{user.first_name} {user.last_name}',
                },
                '$categories': list(paper.hubs.values_list('slug', flat=True)),
            }
        }

        self.create_meta_properties(post_properties, request)
        track_type = '$update_content' if update else '$create_content'

        try:
            response = client.track(track_type, post_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_vote(self, user, vote, request, update=False):
        vote_type = vote.vote_type
        review_properties = {
            '$user_id': str(user.id),
            '$content_id': f'{type(vote).__name__}_{vote.id}',

            '$status': '$active',

            '$review': {
                '$contact_email': user.email,
                '$rating': vote_type
            }
        }
        self.create_meta_properties(review_properties, request)
        track_type = '$update_content' if update else '$create_content'

        try:
            response = client.track(track_type, review_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_flag_content(self, user, content_id, referer_id):
        # https://sift.com/developers/docs/curl/events-api/reserved-events/flag-content
        properties = {
            '$user_id': str(user.id),
            '$content_id': content_id,
            '$flagged_by': referer_id
        }

        try:
            response = client.track('$flag_content', properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_status(self):
        # https://sift.com/developers/docs/python/events-api/reserved-events/content-status
        # TODO: We might not need this?
        properties = {
            '$user_id': '',
            '$content_id': '',
            '$status': ''
        }


events_api = EventsApi()
